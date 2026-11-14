using System;
using System.ServiceModel;
using System.Diagnostics;

namespace AIST.AuditService
{
    [ServiceContract]
    public interface IAuditService
    {
        [OperationContract]
        string RecordAuditTrail(int ticketId, string action, string user);

        [OperationContract]
        string GetHealthStatus();

        [OperationContract]
        void TriggerChaosCrash();
    }

    public class AuditService : IAuditService
    {
        public string RecordAuditTrail(int ticketId, string action, string user)
        {
            // Writes audit event to Windows Event Log
            string logMessage = $"[AUDIT] Ticket #{ticketId} modified by {user}: Action={action}";
            Trace.WriteLine(logMessage);
            return $"Audit record committed for Ticket #{ticketId}";
        }

        public string GetHealthStatus()
        {
            return "{\"status\":\"HEALTHY\",\"service\":\"audit-service-wcf\",\"framework\":\".NET Framework 4.8\",\"os\":\"Windows Server 2019\"}";
        }

        public void TriggerChaosCrash()
        {
            // Simulates CHAOS-07 unhandled NullReferenceException in WCF
            string nullString = null;
            int length = nullString.Length; // Throws NullReferenceException -> logs Event ID 1026
        }
    }
}
