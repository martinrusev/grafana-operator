#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import unittest

import yaml
from ops.testing import Harness
from charm import GrafanaOperator


BASE_CONFIG = {
    "port": 3000,
    "grafana_log_level": "info",
}


class GrafanaCharmTest(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Harness(GrafanaOperator)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.harness.add_oci_resource("grafana-image")
        self.harness.update_config(BASE_CONFIG)

    def test_grafana_layer(self):

        expected = {
            "summary": "grafana layer",
            "description": "grafana layer",
            "services": {
                "grafana": {
                    "override": "replace",
                    "summary": "grafana service",
                    "command": "grafana-server -config /etc/grafana/conf/grafana.ini",
                    "startup": "enabled",
                    "environment": {
                        "GF_HTTP_PORT": BASE_CONFIG.get("port"),
                        "GF_LOG_LEVEL": BASE_CONFIG.get("port"),
                        "GF_PATHS_PROVISIONING": "/etc/grafana/provisioning",
                    },
                }
            },
        }

        self.assertEqual(set(self.harness.charm._grafana_layer()), set(expected))

    def test__generate_datasource_config(self) -> None:
        result = self.harness.charm._generate_datasource_config()
        # Initial / Empty
        assert yaml.safe_load(result) == {
            "apiVersion": 1,
            "datasources": [],
            "deleteDatasources": [],
        }

        self.harness.charm._stored.sources = {
            "prom": {
                "isDefault": True,
                "source-name": "Prometheus",
                "source-type": "prom",
                "private-address": "192.168.0.1",
                "port": 8000,
            }
        }

        result = self.harness.charm._generate_datasource_config()
        assert yaml.safe_load(result) == {
            "apiVersion": 1,
            "datasources": [
                {
                    "access": "proxy",
                    "isDefault": True,
                    "name": "Prometheus",
                    "orgId": "1",
                    "type": "prom",
                    "url": "http://192.168.0.1:8000",
                }
            ],
            "deleteDatasources": [],
        }

    def test__generate_database_config(self) -> None:
        self.harness.charm._stored.database = {
            "host": "localhost",
            "database": "MYSQL",
            "user": "u7ser",
            "password": "password",
        }
        result = self.harness.charm._generate_database_config()

        expected_result = """[database]
type = mysql
host = localhost
name = MYSQL
user = u7ser
password = password
url = mysql://u7ser:password@localhost/MYSQL"""

        assert result.rstrip() == expected_result

    def test__database_relation_data(self):
        self.harness.set_leader(True)
        self.assertEqual(self.harness.charm._stored.database, {})

        rel_id = self.harness.add_relation("db", "mysql")
        rel = self.harness.model.get_relation("db")
        self.harness.add_relation_unit(rel_id, "mysql/0")
        test_relation_data = {
            "type": "mysql",
            "host": "localhost:3306",
            "database": "my-test-db",
            "user": "test-user",
            "password": "password",
        }

        #   File "ops/testing.py", line 1109, in push
        #     raise NotImplementedError(self.push)

        # self.harness.update_relation_data(rel_id, "mysql/0", test_relation_data)
        # self.assertEqual(dict(self.harness.charm._stored.database), test_relation_data)

        # self.harness.charm.on.database_relation_broken.emit(rel)
        # self.assertEqual({}, dict(self.harness.charm._stored.database))

    def test__grafana_source_data(self):
        self.harness.set_leader(True)
        self.assertEqual(self.harness.charm._stored.sources, {})

        rel_id = self.harness.add_relation("grafana-source", "prometheus")
        self.harness.add_relation_unit(rel_id, "prometheus/0")
        self.assertIsInstance(rel_id, int)

        #   File "ops/testing.py", line 1109, in push
        #     raise NotImplementedError(self.push)

        # self.harness.update_relation_data(
        #     rel_id,
        #     "prometheus/0",
        #     {
        #         "private-address": "192.0.2.1",
        #         "port": 1234,
        #         "source-type": "prometheus",
        #         "source-name": "prometheus-app",
        #     },
        # )

        # expected_first_source_data = {
        #     "private-address": "192.0.2.1",
        #     "port": 1234,
        #     "source-name": "prometheus-app",
        #     "source-type": "prometheus",
        #     "isDefault": "true",
        #     "unit_name": "prometheus/0",
        # }
        # self.assertEqual(
        #     expected_first_source_data, dict(self.harness.charm._stored.sources[rel_id])
        # )

        self.harness.update_relation_data(
            rel_id,
            "prometheus/0",
            {
                "private-address": None,
                "port": None,
            },
        )
        self.assertEqual(None, self.harness.charm._stored.sources.get(rel_id))
