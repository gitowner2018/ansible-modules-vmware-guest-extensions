#!/usr/bin/python

try:
    import pyVmomi
    from pyVmomi import vim
except ImportError:
    pass

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils._text import to_text
from ansible.module_utils.vmware_extensions import AnsibleVMWareGuestNic

def main():

    argument_spec = dict(
        hostname=dict(type='str', required=False),
        username=dict(type='str', aliases=['user', 'admin'], required=False),
        password=dict(type='str', aliases=['pass', 'pwd'], required=False, no_log=True),
        port=dict(type='int', default=443),
        validate_certs=dict(type='bool', required=False, default=True),
        state=dict(type='str' , required=False , default = 'present' , choices = [ 'present' , 'absent' ] ),
        name=dict(type='str' , required=True),
        network=dict(type='str' , required=False),
        ipv4=dict(type='str' , required=True),
        netmask=dict(type='str' , required=False),
        gateway=dict(type='str' , required=False)
    )

    #vmware_required_if = [
    #  [ 'state' , 'present' , [ 'name' , 'network' , 'ipv4' , 'netmask' , 'gateway' ] ] ,
    #  [ 'state' , 'absent' , [ 'name' , ipv4' ] ]
    #]

    module = AnsibleModule(
      argument_spec=argument_spec #,
      #required_if=vmware_required_if
    )

    vmware = AnsibleVMWareGuestNic(module)

    vm = vmware.find_obj( [vim.VirtualMachine] , module.params['name'] )

    if vm:
        try:
            if module.params['state'] == 'absent':
              vmware.deleteVirtualNic( vm )
            else:
              vmware.createVirtualNic( vm )
        except Exception as exc:
            module.fail_json(msg="Fact gather failed with exception %s" % to_text(exc))
    else:
        module.fail_json(msg="Unable to gather facts for non-existing VM %s" % module.params.get('uuid') or module.params.get('name'))

    module.exit_json(**vmware.result)

if __name__ == '__main__':
    main()
