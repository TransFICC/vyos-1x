#!/usr/bin/env python3
#
# Copyright (C) 2021 VyOS maintainers and contributors
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 or later as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import unittest

from vyos.configsession import ConfigSession
from vyos.ifconfig import Section
from vyos.util import cmd
from vyos.util import process_named_running

PROCESS_NAME = 'ripngd'
acl_in = '198'
acl_out = '199'
prefix_list_in = 'foo-prefix'
prefix_list_out = 'bar-prefix'
route_map = 'FooBar123'

base_path = ['protocols', 'ripng']

def getFRRconfig():
    return cmd('vtysh -c "show run" | sed -n "/router ripng/,/^!/p"')

class TestProtocolsRIPng(unittest.TestCase):
    def setUp(self):
        self.session = ConfigSession(os.getpid())

        self.session.set(['policy', 'access-list6', acl_in, 'rule', '10', 'action', 'permit'])
        self.session.set(['policy', 'access-list6', acl_in, 'rule', '10', 'source', 'any'])
        self.session.set(['policy', 'access-list6', acl_out, 'rule', '20', 'action', 'deny'])
        self.session.set(['policy', 'access-list6', acl_out, 'rule', '20', 'source', 'any'])
        self.session.set(['policy', 'prefix-list6', prefix_list_in, 'rule', '100', 'action', 'permit'])
        self.session.set(['policy', 'prefix-list6', prefix_list_in, 'rule', '100', 'prefix', '2001:db8::/32'])
        self.session.set(['policy', 'prefix-list6', prefix_list_out, 'rule', '200', 'action', 'deny'])
        self.session.set(['policy', 'prefix-list6', prefix_list_out, 'rule', '200', 'prefix', '2001:db8::/32'])
        self.session.set(['policy', 'route-map', route_map, 'rule', '10', 'action', 'permit'])

    def tearDown(self):
        self.session.delete(base_path)
        self.session.delete(['policy', 'access-list6', acl_in])
        self.session.delete(['policy', 'access-list6', acl_out])
        self.session.delete(['policy', 'prefix-list6', prefix_list_in])
        self.session.delete(['policy', 'prefix-list6', prefix_list_out])
        self.session.delete(['policy', 'route-map', route_map])

        self.session.commit()
        del self.session

        # Check for running process
        self.assertTrue(process_named_running(PROCESS_NAME))

    def test_ripng(self):
        metric = '8'
        interfaces = Section.interfaces('ethernet')
        aggregates = ['2001:db8:1000::/48', '2001:db8:2000::/48', '2001:db8:3000::/48']
        networks = ['2001:db8:1000::/64', '2001:db8:1001::/64', '2001:db8:2000::/64', '2001:db8:2001::/64']
        redistribute = ['bgp', 'connected', 'kernel', 'ospfv3', 'static']
        timer_garbage = '888'
        timer_timeout = '1000'
        timer_update = '90'

        self.session.set(base_path + ['default-information', 'originate'])
        self.session.set(base_path + ['default-metric', metric])
        self.session.set(base_path + ['distribute-list', 'access-list', 'in', acl_in])
        self.session.set(base_path + ['distribute-list', 'access-list', 'out', acl_out])
        self.session.set(base_path + ['distribute-list', 'prefix-list', 'in', prefix_list_in])
        self.session.set(base_path + ['distribute-list', 'prefix-list', 'out', prefix_list_out])
        self.session.set(base_path + ['passive-interface', 'default'])
        self.session.set(base_path + ['timers', 'garbage-collection', timer_garbage])
        self.session.set(base_path + ['timers', 'timeout', timer_timeout])
        self.session.set(base_path + ['timers', 'update', timer_update])
        for aggregate in aggregates:
            self.session.set(base_path + ['aggregate-address', aggregate])

        for interface in interfaces:
            self.session.set(base_path + ['interface', interface])
            self.session.set(base_path + ['distribute-list', 'interface', interface, 'access-list', 'in', acl_in])
            self.session.set(base_path + ['distribute-list', 'interface', interface, 'access-list', 'out', acl_out])
            self.session.set(base_path + ['distribute-list', 'interface', interface, 'prefix-list', 'in', prefix_list_in])
            self.session.set(base_path + ['distribute-list', 'interface', interface, 'prefix-list', 'out', prefix_list_out])
        for network in networks:
            self.session.set(base_path + ['network', network])
            self.session.set(base_path + ['route', network])
        for proto in redistribute:
            self.session.set(base_path + ['redistribute', proto, 'metric', metric])
            self.session.set(base_path + ['redistribute', proto, 'route-map', route_map])


        # commit changes
        self.session.commit()

        # Verify FRR ospfd configuration
        frrconfig = getFRRconfig()
        self.assertIn(f'router ripng', frrconfig)
        self.assertIn(f' default-information originate', frrconfig)
        self.assertIn(f' default-metric {metric}', frrconfig)
        self.assertIn(f' ipv6 distribute-list {acl_in} in', frrconfig)
        self.assertIn(f' ipv6 distribute-list {acl_out} out', frrconfig)
        self.assertIn(f' ipv6 distribute-list prefix {prefix_list_in} in', frrconfig)
        self.assertIn(f' ipv6 distribute-list prefix {prefix_list_out} out', frrconfig)
        self.assertIn(f' passive-interface default', frrconfig)
        self.assertIn(f' timers basic {timer_update} {timer_timeout} {timer_garbage}', frrconfig)
        for aggregate in aggregates:
            self.assertIn(f' aggregate-address {aggregate}', frrconfig)
        for interface in interfaces:
            self.assertIn(f' network {interface}', frrconfig)
            self.assertIn(f' ipv6 distribute-list {acl_in} in {interface}', frrconfig)
            self.assertIn(f' ipv6 distribute-list {acl_out} out {interface}', frrconfig)
            self.assertIn(f' ipv6 distribute-list prefix {prefix_list_in} in {interface}', frrconfig)
            self.assertIn(f' ipv6 distribute-list prefix {prefix_list_out} out {interface}', frrconfig)
        for network in networks:
            self.assertIn(f' network {network}', frrconfig)
            self.assertIn(f' route {network}', frrconfig)
        for proto in redistribute:
            if proto == 'ospfv3':
                proto = 'ospf6'
            self.assertIn(f' redistribute {proto} metric {metric} route-map {route_map}', frrconfig)

if __name__ == '__main__':
    unittest.main(verbosity=2)
