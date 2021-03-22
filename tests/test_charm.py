#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import unittest

# from ops.model import (
#     TooManyRelatedAppsError
# )
from ops.testing import Harness
from charm import GrafanaOperator


BASE_CONFIG = {
    'port': 3000,
    'grafana_log_level': 'info',
}


class GrafanaCharmTest(unittest.TestCase):

    def setUp(self) -> None:
        self.harness = Harness(GrafanaOperator)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.harness.add_oci_resource('grafana-image')

    def test__database_relation_data(self):
        self.harness.set_leader(True)
        self.harness.update_config(BASE_CONFIG)
        self.assertEqual(self.harness.charm.datastore.database, {})

        # add relation and update relation data
        rel_id = self.harness.add_relation('database', 'mysql')
        rel = self.harness.model.get_relation('database')
        self.harness.add_relation_unit(rel_id, 'mysql/0')
        test_relation_data = {
            'type': 'mysql',
            'host': '0.1.2.3:3306',
            'name': 'my-test-db',
            'user': 'test-user',
            'password': 'super!secret!password',
        }
        self.harness.update_relation_data(rel_id,
                                          'mysql/0',
                                          test_relation_data)
        # check that charm datastore was properly set
        self.assertEqual(dict(self.harness.charm.datastore.database),
                         test_relation_data)

        # now depart this relation and ensure the datastore is emptied
        self.harness.charm.on.database_relation_broken.emit(rel)
        self.assertEqual({}, dict(self.harness.charm.datastore.database))

    # def test__multiple_database_relation_handling(self):
    #     self.harness.set_leader(True)
    #     self.harness.update_config(BASE_CONFIG)
    #     self.assertEqual(self.harness.charm.datastore.database, {})

    #     # add first database relation
    #     self.harness.add_relation('database', 'mysql')

    #     # add second database relation -- should fail here
    #     with self.assertRaises(TooManyRelatedAppsError):
    #         self.harness.add_relation('database', 'mysql')
    #         self.harness.charm.model.get_relation('database')
