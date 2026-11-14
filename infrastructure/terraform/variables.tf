variable "vsphere_server" {
  type    = string
  default = "192.168.1.220"
}

variable "vsphere_user" {
  type    = string
  default = "Administrator@vsphere.local"
}

variable "vsphere_password" {
  type      = string
  default   = "Root@123"
  sensitive = true
}

variable "datastore_name" {
  type    = string
  default = "Base_DS"
}

