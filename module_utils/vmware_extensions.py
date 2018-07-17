#!/usr/bin/python

import requests
import atexit
import ssl
import requests
import json

from pyVim import connect
from pyVim.connect import SmartConnect
from pyVmomi import vim, vmodl
from ansible.module_utils.basic import AnsibleModule

class AnsibleVMWareGuestNic( object ):


  def __init__( self , module ):

    self.module = module
    self.result = { 'changed' : False }
    self.params = module.params
    self.sslVerify = ssl.SSLContext( ssl.PROTOCOL_TLSv1 )
    self.sslVerify.verify_mode = ssl.CERT_NONE
    self.service_instance = SmartConnect( host = self.params['hostname'] , user = self.params['username'] , pwd = self.params['password'] , sslContext = self.sslVerify )
    self.content = self.service_instance.content


  def find_obj( self , vimtype, name, first=True):
    container = self.content.viewManager.CreateContainerView(container=self.content.rootFolder, recursive=True, type=vimtype)
    obj_list = container.view
    container.Destroy()

    # Backward compatible with former get_obj() function
    if name is None:
      if obj_list:
        return obj_list[0]
      return None

    # Select the first match
    if first is True:
      for obj in obj_list:
        if obj.name == name:
          return obj

      # If no object found, return None
      return None

    # Return all matching objects if needed
    return [obj for obj in obj_list if obj.name == name]


  def wait_for_tasks( self , service_instance, tasks ):
      
    property_collector = service_instance.content.propertyCollector
    task_list = [str(task) for task in tasks]

    # Create filter
    obj_specs = [vmodl.query.PropertyCollector.ObjectSpec(obj=task) for task in tasks]
    property_spec = vmodl.query.PropertyCollector.PropertySpec(type=vim.Task , pathSet=[] , all=True)

    filter_spec = vmodl.query.PropertyCollector.FilterSpec()
    filter_spec.objectSet = obj_specs
    filter_spec.propSet = [property_spec]

    pcfilter = property_collector.CreateFilter(filter_spec, True)

    try:
      version, state = None, None
      # Loop looking for updates till the state moves to a completed state.
      while len(task_list):
        update = property_collector.WaitForUpdates(version)
        for filter_set in update.filterSet:
          for obj_set in filter_set.objectSet:
            task = obj_set.obj
            for change in obj_set.changeSet:
              if change.name == 'info':
                state = change.val.state
              elif change.name == 'info.state':
                state = change.val
              else:
                continue
  
              if not str(task) in task_list:
                continue
  
              if state == vim.TaskInfo.State.success:
                # Remove task from taskList
                task_list.remove(str(task))
              elif state == vim.TaskInfo.State.error:
                raise task.info.error
        # Move to next version
        version = update.version
    finally:
      if pcfilter:
        pcfilter.Destroy()


  def getVirtualMachineNicCount( self , vm ):
    
    count = 0

    for attr in vm.config.hardware.device:
      if isinstance(attr, vim.vm.device.VirtualEthernetCard):
        count += 1

    return count


  def getMacAddressList( self , vm ):

    addresses = []

    while len(addresses) == 0:
      for mac in vm.guest.net:
        addresses.append(mac.macAddress)

    return addresses


  def getDifference( self , list1 , list2 ):

    diff = None

    for itm in list1:
      if itm not in list2:
        diff = itm

    return diff


  def getVirtualMachineNicFacts( self , vm ):

    facts = {
      'guest'		: vm.guest.hostName,
      'label'           : None,
      'device'          : None,
      'macAddress'      : None,
      'ipv4'            : None,
      'ipv6'            : None,
      'connected'       : None,
      'state'           : None
    }


    # IPv4 Address via MAC Address
    for ipv4 in vm.guest.net:
      if str(ipv4.ipAddress[0]) == self.module.params['ipv4']:
        facts['macAddress'] = ipv4.macAddress
        facts['ipv4'] = str(ipv4.ipAddress[0])
        facts['ipv6'] = str(ipv4.ipAddress[1])
        facts['connected'] = str(ipv4.connected)


    for attr in vm.config.hardware.device:
      if isinstance(attr, vim.vm.device.VirtualEthernetCard):
        if attr.macAddress == facts['macAddress']:
          facts['label'] = attr.deviceInfo.label
          facts['device'] = attr.backing.deviceName
          facts['state'] = attr.connectable.status

    return facts
 

  def gatherNicFacts( self , vm ):
    facts = getVirtualMachineNicFacts( vm )
    self.module.exit_json( msg=facts )


  def deleteVirtualNic( self , vm ):
     
    nic_count = self.getVirtualMachineNicCount( vm )

    if nic_count == 1:
      self.result['changed'] = False
      self.module.fail_json( msg='There is only 1 Network Interface attached to this Virtual Machine. So, we wont be deleting it.' )

    nic = None
    
    nic_facts = self.getVirtualMachineNicFacts( vm )
    nic_label = nic_facts['label']

    for dev in vm.config.hardware.device:
      if isinstance(dev, vim.vm.device.VirtualEthernetCard):
        if dev.deviceInfo.label == nic_label:
          nic = dev

    if not nic:
      self.result['changed'] = False
      self.module.exit_json( msg='Network Interface with ip ' + self.module.params['ipv4'] + ' not found. Nic Count ')

    virtual_nic_spec = vim.vm.device.VirtualDeviceSpec()
    virtual_nic_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.remove
    virtual_nic_spec.device = nic

    spec = vim.vm.ConfigSpec()
    spec.deviceChange = [virtual_nic_spec]

    task = vm.ReconfigVM_Task(spec=spec)
    self.wait_for_tasks(self.service_instance, [task])

    self.result['changed'] = True



  def createVirtualNic( self , vm ):

    configSpec = vim.vm.ConfigSpec()
    nicSpecProperties = []

    nicSpec = vim.vm.device.VirtualDeviceSpec()
    nicSpec.operation = vim.vm.device.VirtualDeviceSpec.Operation.add

    nicSpec.device = vim.vm.device.VirtualVmxnet3()
    nicSpec.device.deviceInfo = vim.Description()
    nicSpec.device.deviceInfo.summary = self.module.params['network']

    # Make sure the network exists
    network = self.find_obj( [vim.Network], self.module.params['network'] )

    if not network:
      self.result['changed'] = False
      self.module.fail_json( msg='Unable to find network: ' + self.module.params['network'] )
    else:
      nicSpec.device.backing = vim.vm.device.VirtualEthernetCard.NetworkBackingInfo()
      nicSpec.device.backing.useAutoDetect = False
      nicSpec.device.backing.network = network
      nicSpec.device.backing.deviceName = self.module.params['network']

    # Setting Default Properties for the new NIC
    nicSpec.device.connectable = vim.vm.device.VirtualDevice.ConnectInfo()
    nicSpec.device.connectable.startConnected = True
    nicSpec.device.connectable.allowGuestControl = True
    nicSpec.device.connectable.connected = False
    nicSpec.device.connectable.status = 'untried'
    nicSpec.device.wakeOnLanEnabled = True
    nicSpec.device.addressType = 'assigned'

    nicSpecProperties.append(nicSpec)
    configSpec.deviceChange = nicSpecProperties

    # Add the NIC and wait for the task to complete in vCenter
    macPreSnapshot = self.getMacAddressList( vm )
    task = vm.ReconfigVM_Task(spec=configSpec)
    self.wait_for_tasks(self.service_instance, [task])

    response = {}
    macPostSnapshot = self.getMacAddressList( vm )
    newMacAddress = self.getDifference( macPostSnapshot , macPreSnapshot )
    response['macAddress'] = newMacAddress
    
    self.result['msg'] = response
    self.result['changed'] = True
