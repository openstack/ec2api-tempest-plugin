# Copyright 2014 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from oslo_log import log
from tempest_lib.common.utils import data_utils
import testtools

from ec2api.tests.functional import base
from ec2api.tests.functional import config

CONF = config.CONF
LOG = log.getLogger(__name__)


class InstanceTest(base.EC2TestCase):

    @classmethod
    @base.safe_setup
    def setUpClass(cls):
        super(InstanceTest, cls).setUpClass()
        if not CONF.aws.image_id:
            raise cls.skipException('aws image_id does not provided')
        cls.zone = CONF.aws.aws_zone

    def test_create_delete_instance(self):
        instance_type = CONF.aws.instance_type
        image_id = CONF.aws.image_id
        data = self.client.run_instances(
            ImageId=image_id, InstanceType=instance_type,
            Placement={'AvailabilityZone': self.zone}, MinCount=1, MaxCount=1)
        instance_id = data['Instances'][0]['InstanceId']
        res_clean = self.addResourceCleanUp(self.client.terminate_instances,
                                            InstanceIds=[instance_id])
        self.assertEqual(1, len(data['Instances']))
        self.get_instance_waiter().wait_available(instance_id,
                                                  final_set=('running'))

        data = self.client.describe_instances(InstanceIds=[instance_id])
        reservations = data.get('Reservations', [])
        self.assertNotEmpty(reservations)
        instances = reservations[0].get('Instances', [])
        self.assertEqual(1, len(instances))

        self.client.terminate_instances(InstanceIds=[instance_id])
        self.cancelResourceCleanUp(res_clean)
        self.get_instance_waiter().wait_delete(instance_id)

        # NOTE(andrey-mp): There is difference between Openstack and Amazon.
        # Amazon returns instance in 'terminated' state some time after
        # instance deletion. But Openstack doesn't return such instance.

    def test_create_idempotent_instance(self):
        client_token = data_utils.rand_name('t')
        instance_type = CONF.aws.instance_type
        image_id = CONF.aws.image_id
        data = self.client.run_instances(
            ImageId=image_id, InstanceType=instance_type,
            Placement={'AvailabilityZone': self.zone}, MinCount=1, MaxCount=1,
            ClientToken=client_token)
        instance_id = data['Instances'][0]['InstanceId']
        res_clean = self.addResourceCleanUp(self.client.terminate_instances,
                                            InstanceIds=[instance_id])
        self.assertEqual(1, len(data['Instances']))
        reservation_id = data['ReservationId']
        self.get_instance_waiter().wait_available(instance_id,
                                                  final_set=('running'))

        data = self.client.run_instances(
            ImageId=image_id, InstanceType=instance_type,
            Placement={'AvailabilityZone': self.zone}, MinCount=1, MaxCount=1,
            ClientToken=client_token)

        # NOTE(andrey-mp): if idempotent run will fail this will terminate
        # second instance
        self.addResourceCleanUp(self.client.terminate_instances,
            InstanceIds=[data['Instances'][0]['InstanceId']])

        self.assertEqual(1, len(data['Instances']))
        self.assertEqual(reservation_id, data['ReservationId'])
        self.assertEqual(instance_id, data['Instances'][0]['InstanceId'])

        self.client.terminate_instances(InstanceIds=[instance_id])
        self.cancelResourceCleanUp(res_clean)
        self.get_instance_waiter().wait_delete(instance_id)

    def test_describe_instances_filter(self):
        instance_type = CONF.aws.instance_type
        image_id = CONF.aws.image_id
        data = self.client.run_instances(
            ImageId=image_id, InstanceType=instance_type,
            Placement={'AvailabilityZone': self.zone}, MinCount=1, MaxCount=1)
        instance_id = data['Instances'][0]['InstanceId']
        res_clean = self.addResourceCleanUp(self.client.terminate_instances,
                                            InstanceIds=[instance_id])
        self.get_instance_waiter().wait_available(instance_id,
                                                  final_set=('running'))

        # NOTE(andrey-mp): by real id
        data = self.client.describe_instances(InstanceIds=[instance_id])
        self._assert_instance(data, instance_id)
        instances = data['Reservations'][0]['Instances']
        private_dns = instances[0]['PrivateDnsName']
        private_ip = instances[0]['PrivateIpAddress']

        # NOTE(andrey-mp): by fake id
        self.assertRaises('InvalidInstanceID.NotFound',
                          self.client.describe_instances,
                          InstanceIds=['i-0'])

        # NOTE(andrey-mp): by private ip
        data = self.client.describe_instances(
            Filters=[{'Name': 'private-ip-address', 'Values': ['1.2.3.4']}])
        self.assertEqual(0, len(data['Reservations']))

        data = self.client.describe_instances(
            Filters=[{'Name': 'private-ip-address', 'Values': [private_ip]}])
        self._assert_instance(data, instance_id)

        # NOTE(andrey-mp): by private dns
        data = self.client.describe_instances(
            Filters=[{'Name': 'private-dns-name', 'Values': ['fake.com']}])
        self.assertEqual(0, len(data['Reservations']))

        data = self.client.describe_instances(
            Filters=[{'Name': 'private-dns-name', 'Values': [private_dns]}])
        self._assert_instance(data, instance_id)

        self.client.terminate_instances(InstanceIds=[instance_id])
        self.cancelResourceCleanUp(res_clean)
        self.get_instance_waiter().wait_delete(instance_id)

    def _assert_instance(self, data, instance_id):
        reservations = data.get('Reservations', [])
        self.assertNotEmpty(reservations)
        instances = reservations[0].get('Instances', [])
        self.assertNotEmpty(instances)
        self.assertEqual(instance_id, instances[0]['InstanceId'])

    def test_get_password_data_and_console_output(self):
        instance_type = CONF.aws.instance_type
        image_id = CONF.aws.image_id
        data = self.client.run_instances(
            ImageId=image_id, InstanceType=instance_type,
            Placement={'AvailabilityZone': self.zone}, MinCount=1, MaxCount=1)
        instance_id = data['Instances'][0]['InstanceId']
        res_clean = self.addResourceCleanUp(self.client.terminate_instances,
                                            InstanceIds=[instance_id])
        self.get_instance_waiter().wait_available(instance_id,
                                                  final_set=('running'))

        data = self.client.get_password_data(InstanceId=instance_id)
        self.assertEqual(instance_id, data['InstanceId'])
        self.assertIsNotNone(data['Timestamp'])
        self.assertIn('PasswordData', data)

        waiter = base.EC2Waiter(self.client.get_console_output)
        waiter.wait_no_exception(InstanceId=instance_id)

        data = self.client.get_console_output(InstanceId=instance_id)
        self.assertEqual(instance_id, data['InstanceId'])
        self.assertIsNotNone(data['Timestamp'])
        self.assertIn('Output', data)

        self.client.terminate_instances(InstanceIds=[instance_id])
        self.cancelResourceCleanUp(res_clean)
        self.get_instance_waiter().wait_delete(instance_id)

    def test_stop_instance(self):
        instance_type = CONF.aws.instance_type
        image_id = CONF.aws.image_id
        data = self.client.run_instances(
            ImageId=image_id, InstanceType=instance_type,
            Placement={'AvailabilityZone': self.zone}, MinCount=1, MaxCount=1)
        instance_id = data['Instances'][0]['InstanceId']
        res_clean = self.addResourceCleanUp(self.client.terminate_instances,
                                            InstanceIds=[instance_id])
        self.get_instance_waiter().wait_available(instance_id,
                                                  final_set=('running'))

        data = self.client.stop_instances(InstanceIds=[instance_id])
        if CONF.aws.run_incompatible_tests:
            instances = data['StoppingInstances']
            self.assertEqual(1, len(instances))
            instance = instances[0]
            self.assertEqual(instance_id, instance['InstanceId'])
            self.assertEqual('running', instance['PreviousState']['Name'])
            self.assertEqual('stopping', instance['CurrentState']['Name'])

        self.get_instance_waiter().wait_available(instance_id,
                                                  final_set=('stopped'))

        self.client.terminate_instances(InstanceIds=[instance_id])
        self.cancelResourceCleanUp(res_clean)
        self.get_instance_waiter().wait_delete(instance_id)

    @testtools.skipUnless(CONF.aws.run_incompatible_tests,
        "Openstack doesn't assign public ip automatically for new instance")
    def test_public_ip_is_assigned(self):
        """Is public IP assigned to launched instnace?"""
        instance_type = CONF.aws.instance_type
        image_id = CONF.aws.image_id
        data = self.client.run_instances(
            ImageId=image_id, InstanceType=instance_type,
            Placement={'AvailabilityZone': self.zone}, MinCount=1, MaxCount=1)
        self.assertEqual(1, len(data['Instances']))
        instance_id = data['Instances'][0]['InstanceId']
        res_clean = self.addResourceCleanUp(self.client.terminate_instances,
                                            InstanceIds=[instance_id])
        self.get_instance_waiter().wait_available(instance_id,
                                                  final_set=('running'))

        instance = self.get_instance(instance_id)
        self.assertIsNotNone(instance.get('PublicIpAddress'))
        self.assertIsNotNone(instance.get('PrivateIpAddress'))
        self.assertNotEqual(instance.get('PublicIpAddress'),
                            instance.get('PrivateIpAddress'))

        self.client.terminate_instances(InstanceIds=[instance_id])
        self.cancelResourceCleanUp(res_clean)
        self.get_instance_waiter().wait_delete(instance_id)

    @testtools.skipUnless(CONF.aws.ebs_image_id, "EBS image id is not defined")
    def test_describe_instance_attributes(self):
        instance_type = CONF.aws.instance_type
        image_id = CONF.aws.ebs_image_id
        instance_id = self.run_instance(ImageId=image_id)

        data = self.client.describe_instance_attribute(
            InstanceId=instance_id, Attribute='blockDeviceMapping')
        bdms = data.get('BlockDeviceMappings', [])
        self.assertNotEmpty(bdms)
        self.assertEqual(1, len(bdms))
        self.assertIn('DeviceName', bdms[0])
        self.assertIn('Ebs', bdms[0])

        data = self.client.describe_instance_attribute(
            InstanceId=instance_id, Attribute='disableApiTermination')
        self.assertIn('DisableApiTermination', data)
        self.assertIn('Value', data['DisableApiTermination'])
        self.assertFalse(data['DisableApiTermination']['Value'])

        data = self.client.describe_instance_attribute(
            InstanceId=instance_id, Attribute='groupSet')
        self.assertIn('Groups', data)
        self.assertNotEmpty(data['Groups'], data)
        self.assertTrue('GroupId' in data['Groups'][0]
                        or 'GroupName' in data['Groups'][0])
        self.assertTrue(data['Groups'][0].get('GroupId')
                        or data['Groups'][0].get('GroupName'))

        data = self.client.describe_instance_attribute(
            InstanceId=instance_id, Attribute='instanceType')
        self.assertIn('InstanceType', data)
        self.assertIn('Value', data['InstanceType'])
        self.assertEqual(instance_type, data['InstanceType']['Value'])

        data = self.client.describe_instance_attribute(
            InstanceId=instance_id, Attribute='kernel')
        self.assertIn('KernelId', data)

        data = self.client.describe_instance_attribute(
            InstanceId=instance_id, Attribute='ramdisk')
        self.assertIn('RamdiskId', data)

        data = self.client.describe_instance_attribute(
            InstanceId=instance_id, Attribute='rootDeviceName')
        self.assertIn('RootDeviceName', data)
        self.assertIn('Value', data['RootDeviceName'])
        self.assertTrue(data['RootDeviceName']['Value'])

        self.client.terminate_instances(InstanceIds=[instance_id])
        self.get_instance_waiter().wait_delete(instance_id)

    @testtools.skipUnless(CONF.aws.run_incompatible_tests,
        "Error from nova: "
        "Invalid input for field/attribute 0. ...")
    def test_launch_instance_with_creating_blank_volume(self):
        """Launch instance with creating blank volume."""
        device_name = '/dev/xvdh'
        instance_type = CONF.aws.instance_type
        data = self.client.run_instances(
            ImageId=CONF.aws.image_id, InstanceType=instance_type,
            Placement={'AvailabilityZone': self.zone}, MinCount=1, MaxCount=1,
            BlockDeviceMappings=[{'DeviceName': device_name,
                                  'Ebs': {'VolumeSize': 1}}])
        instance_id = data['Instances'][0]['InstanceId']
        res_clean = self.addResourceCleanUp(self.client.terminate_instances,
                                            InstanceIds=[instance_id])
        self.get_instance_waiter().wait_available(instance_id,
                                                  final_set=('running'))

        bdt = self.get_instance_bdm(instance_id, device_name)
        self.assertIsNotNone(bdt)
        volume_id = bdt['Ebs'].get('VolumeId')
        self.assertIsNotNone(volume_id)
        self.assertTrue(bdt['Ebs']['DeleteOnTermination'])

        data = self.client.describe_volumes(VolumeIds=[volume_id])
        self.assertEqual(1, len(data['Volumes']))
        volume = data['Volumes'][0]
        self.assertEqual(1, volume['Size'])

        self.client.terminate_instances(InstanceIds=[instance_id])
        self.cancelResourceCleanUp(res_clean)
        self.get_instance_waiter().wait_delete(instance_id)

    @testtools.skipUnless(CONF.aws.image_id, "image id is not defined")
    def test_disable_api_termination_attribute(self):
        instance_type = CONF.aws.instance_type
        image_id = CONF.aws.image_id
        data = self.client.run_instances(MinCount=1, MaxCount=1,
            ImageId=image_id, InstanceType=instance_type,
            Placement={'AvailabilityZone': CONF.aws.aws_zone},
            DisableApiTermination=True)
        instance_id = data['Instances'][0]['InstanceId']
        res_clean = self.addResourceCleanUp(self.client.terminate_instances,
                                            InstanceIds=[instance_id])
        self.addResourceCleanUp(self.client.modify_instance_attribute,
                                InstanceId=instance_id,
                                DisableApiTermination={'Value': True})
        self.assertEqual(1, len(data['Instances']))
        self.get_instance_waiter().wait_available(instance_id,
                                                  final_set=('running'))

        data = self.client.describe_instance_attribute(
            InstanceId=instance_id, Attribute='disableApiTermination')
        self.assertIn('DisableApiTermination', data)
        self.assertIn('Value', data['DisableApiTermination'])
        self.assertTrue(data['DisableApiTermination']['Value'])

        data = self.client.modify_instance_attribute(InstanceId=instance_id,
            Attribute='disableApiTermination', Value='False')
        data = self.client.describe_instance_attribute(
            InstanceId=instance_id, Attribute='disableApiTermination')
        self.assertFalse(data['DisableApiTermination']['Value'])

        data = self.client.modify_instance_attribute(InstanceId=instance_id,
            Attribute='disableApiTermination', Value='True')
        data = self.client.describe_instance_attribute(
            InstanceId=instance_id, Attribute='disableApiTermination')
        self.assertTrue(data['DisableApiTermination']['Value'])

        self.assertRaises('OperationNotPermitted',
                          self.client.terminate_instances,
                          InstanceIds=[instance_id])

        data = self.client.modify_instance_attribute(InstanceId=instance_id,
            DisableApiTermination={'Value': False})
        data = self.client.describe_instance_attribute(
            InstanceId=instance_id, Attribute='disableApiTermination')
        self.assertFalse(data['DisableApiTermination']['Value'])

        self.client.terminate_instances(InstanceIds=[instance_id])
        self.cancelResourceCleanUp(res_clean)
        self.get_instance_waiter().wait_delete(instance_id)

    @testtools.skipUnless(CONF.aws.image_id, "image id is not defined")
    def test_instance_attributes_negative(self):
        instance_type = CONF.aws.instance_type
        image_id = CONF.aws.image_id
        data = self.client.run_instances(MinCount=1, MaxCount=1,
            ImageId=image_id, InstanceType=instance_type,
            Placement={'AvailabilityZone': CONF.aws.aws_zone})
        instance_id = data['Instances'][0]['InstanceId']
        res_clean = self.addResourceCleanUp(self.client.terminate_instances,
                                            InstanceIds=[instance_id])
        self.assertEqual(1, len(data['Instances']))
        self.get_instance_waiter().wait_available(instance_id,
                                                  final_set=('running'))

        self.assertRaises('InvalidParameterValue',
            self.client.describe_instance_attribute,
            InstanceId=instance_id, Attribute='fake_attribute')
        self.assertRaises('InvalidInstanceID.NotFound',
            self.client.describe_instance_attribute,
            InstanceId='i-0', Attribute='disableApiTermination')

        self.assertRaises('InvalidParameterValue',
            self.client.modify_instance_attribute,
            InstanceId=instance_id, Attribute='fake_attribute')
        self.assertRaises('MissingParameter',
            self.client.modify_instance_attribute,
            InstanceId=instance_id, Attribute='disableApiTermination')
        self.assertRaises('InvalidParameterCombination',
            self.client.modify_instance_attribute,
            InstanceId=instance_id)
        self.assertRaises('InvalidParameterCombination',
            self.client.modify_instance_attribute,
            InstanceId=instance_id, Attribute='disableApiTermination',
            Value='True', DisableApiTermination={'Value': False})

        self.assertRaises('InvalidParameterValue',
            self.client.reset_instance_attribute,
            InstanceId=instance_id, Attribute='fake_attribute')
        self.assertRaises('InvalidParameterValue',
            self.client.reset_instance_attribute,
            InstanceId=instance_id, Attribute='disableApiTermination')
        self.assertRaises('InvalidParameterValue',
            self.client.reset_instance_attribute,
            InstanceId='i-0', Attribute='disableApiTermination')

        self.client.terminate_instances(InstanceIds=[instance_id])
        self.cancelResourceCleanUp(res_clean)
        self.get_instance_waiter().wait_delete(instance_id)
