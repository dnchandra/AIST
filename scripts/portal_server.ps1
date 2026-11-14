$prefix = 'http://+:3000/'
$root = 'C:\AIST\LoanPortal'
$targetApi = 'http://192.168.1.130:5000'

# Ensure HTTP.sys ACL
netsh http add urlacl url=$prefix user=Everyone 2>$null | Out-Null

$csharp = @"
using System;
using System.IO;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;

public class NativePortalServer
{
    private HttpListener _listener;
    private string _root;
    private string _targetApi;
    private bool _running;
    private static readonly Regex ApiRegex = new Regex(@"^/(ask|chat|cases|applications|business-metrics|customers|documents|local-documents|process|decide|rag|healthz|metrics|admin|readyz)(/|$|\?)", RegexOptions.IgnoreCase | RegexOptions.Compiled);

    public NativePortalServer(string prefix, string root, string targetApi)
    {
        _root = root;
        _targetApi = targetApi;
        _listener = new HttpListener();
        _listener.Prefixes.Add(prefix);
    }

    public void Start()
    {
        _listener.Start();
        _running = true;
        ThreadPool.QueueUserWorkItem(new WaitCallback(async state => await ListenLoop()));
    }

    public void Stop()
    {
        _running = false;
        try { _listener.Stop(); } catch {}
    }

    private async Task ListenLoop()
    {
        while (_running && _listener.IsListening)
        {
            try
            {
                var context = await _listener.GetContextAsync();
                ThreadPool.QueueUserWorkItem(new WaitCallback(state => HandleRequest(context)));
            }
            catch
            {
                if (!_running) break;
            }
        }
    }

    private void HandleRequest(HttpListenerContext context)
    {
        var req = context.Request;
        var res = context.Response;

        try
        {
            // CORS headers
            res.Headers["Access-Control-Allow-Origin"] = "*";
            res.Headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH";
            res.Headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, Accept";

            if (req.HttpMethod == "OPTIONS")
            {
                res.StatusCode = 204;
                res.Close();
                return;
            }

            string rawUrl = req.RawUrl ?? "/";
            if (ApiRegex.IsMatch(rawUrl))
            {
                ProxyApiRequest(context, rawUrl);
                return;
            }

            ServeStatic(context, req.Url.AbsolutePath);
        }
        catch (Exception ex)
        {
            try
            {
                res.StatusCode = 500;
                byte[] err = Encoding.UTF8.GetBytes("500 Server Error: " + ex.Message);
                res.OutputStream.Write(err, 0, err.Length);
                res.Close();
            }
            catch {}
        }
    }

    private void ProxyApiRequest(HttpListenerContext context, string rawUrl)
    {
        var req = context.Request;
        var res = context.Response;

        try
        {
            string dest = _targetApi.TrimEnd('/') + rawUrl;
            var proxyReq = (HttpWebRequest)WebRequest.Create(dest);
            proxyReq.Method = req.HttpMethod;
            proxyReq.Timeout = 900000;
            proxyReq.ReadWriteTimeout = 900000;
            proxyReq.KeepAlive = false;

            if (!string.IsNullOrEmpty(req.ContentType))
                proxyReq.ContentType = req.ContentType;
            if (!string.IsNullOrEmpty(req.UserAgent))
                proxyReq.UserAgent = req.UserAgent;

            if (req.HasEntityBody && req.InputStream != null)
            {
                byte[] bodyBytes;
                using (var ms = new MemoryStream())
                {
                    req.InputStream.CopyTo(ms);
                    bodyBytes = ms.ToArray();
                }
                proxyReq.ContentLength = bodyBytes.Length;
                if (bodyBytes.Length > 0)
                {
                    using (var proxyStream = proxyReq.GetRequestStream())
                    {
                        proxyStream.Write(bodyBytes, 0, bodyBytes.Length);
                    }
                }
            }
            else if (proxyReq.Method == "POST" || proxyReq.Method == "PUT" || proxyReq.Method == "PATCH")
            {
                proxyReq.ContentLength = 0;
            }

            HttpWebResponse proxyRes = null;
            WebException savedWex = null;
            try
            {
                proxyRes = (HttpWebResponse)proxyReq.GetResponse();
            }
            catch (WebException wex)
            {
                savedWex = wex;
                proxyRes = (HttpWebResponse)wex.Response;
            }

            if (proxyRes != null)
            {
                res.StatusCode = (int)proxyRes.StatusCode;
                if (!string.IsNullOrEmpty(proxyRes.ContentType))
                    res.ContentType = proxyRes.ContentType;

                using (var inStream = proxyRes.GetResponseStream())
                {
                    if (inStream != null)
                    {
                        inStream.CopyTo(res.OutputStream);
                    }
                }
                proxyRes.Close();
            }
            else
            {
                res.StatusCode = 502;
                string msg = savedWex != null ? savedWex.Message : "Backend unreachable";
                byte[] b = Encoding.UTF8.GetBytes("{\"error\": \"Backend unreachable: " + msg.Replace("\"", "\\\"") + "\"}");
                res.ContentType = "application/json";
                res.OutputStream.Write(b, 0, b.Length);
            }
        }
        catch (Exception ex)
        {
            res.StatusCode = 500;
            byte[] b = Encoding.UTF8.GetBytes("{\"error\": \"" + ex.Message.Replace("\"", "\\\"") + "\"}");
            res.ContentType = "application/json";
            res.OutputStream.Write(b, 0, b.Length);
        }
        finally
        {
            try { res.Close(); } catch {}
        }
    }

    private void ServeStatic(HttpListenerContext context, string absPath)
    {
        var res = context.Response;
        try
        {
            string rel = absPath.TrimStart('/');
            if (string.IsNullOrEmpty(rel)) rel = "index.html";

            string filePath = Path.Combine(_root, rel.Replace('/', Path.DirectorySeparatorChar));
            if (!File.Exists(filePath))
            {
                filePath = Path.Combine(_root, "index.html");
            }

            if (!File.Exists(filePath))
            {
                res.StatusCode = 200;
                res.ContentType = "text/html; charset=utf-8";
                byte[] b = Encoding.UTF8.GetBytes("<h1>LoanProcessAI Portal</h1><p>Initializing...</p>");
                res.OutputStream.Write(b, 0, b.Length);
                res.Close();
                return;
            }

            string ext = Path.GetExtension(filePath).ToLowerInvariant();
            switch (ext)
            {
                case ".html": res.ContentType = "text/html; charset=utf-8"; break;
                case ".js":   res.ContentType = "application/javascript"; break;
                case ".css":  res.ContentType = "text/css"; break;
                case ".json": res.ContentType = "application/json"; break;
                case ".svg":  res.ContentType = "image/svg+xml"; break;
                case ".png":  res.ContentType = "image/png"; break;
                case ".ico":  res.ContentType = "image/x-icon"; break;
                case ".map":  res.ContentType = "application/json"; break;
                default:      res.ContentType = "application/octet-stream"; break;
            }

            byte[] fileBytes = File.ReadAllBytes(filePath);
            res.ContentLength64 = fileBytes.Length;
            res.StatusCode = 200;
            res.OutputStream.Write(fileBytes, 0, fileBytes.Length);
        }
        catch (Exception ex)
        {
            res.StatusCode = 500;
            byte[] b = Encoding.UTF8.GetBytes("500 Error: " + ex.Message);
            res.OutputStream.Write(b, 0, b.Length);
        }
        finally
        {
            try { res.Close(); } catch {}
        }
    }
}
"@

Add-Type -TypeDefinition $csharp -Language CSharp

$server = New-Object NativePortalServer($prefix, $root, $targetApi)
$server.Start()

Write-Host "Native C# LoanProcessAI Portal Server & Reverse Proxy running on $prefix"

while ($true) {
    Start-Sleep -Seconds 10
}
