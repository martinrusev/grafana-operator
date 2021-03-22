#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import logging

from ops.charm import CharmBase
from ops.main import main
from ops.framework import StoredState
from ops.model import ActiveStatus


logger = logging.getLogger(__name__)

REQUIRED_DATABASE_FIELDS = {
    "type",  # mysql, postgres or sqlite3 (sqlite3 doesn't work for HA)
    "host",  # in the form '<url_or_ip>:<port>', e.g. 127.0.0.1:3306
    "name",
    "user",
    "password",
}

VALID_DATABASE_TYPES = {"mysql", "postgres", "sqlite3"}


class GrafanaOperator(CharmBase):
    """Charm to run Grafana on Kubernetes.

    This charm allows for high-availability
    (as long as a non-sqlite database relation is present).

    Developers of this charm should be aware of the Grafana provisioning docs:
    https://grafana.com/docs/grafana/latest/administration/provisioning/
    """

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(
            self.on.grafana_pebble_ready, self._on_grafana_pebble_ready
        )

        # -- database relation observations
        self.framework.observe(
            self.on["database"].relation_changed, self.on_database_changed
        )
        self.framework.observe(
            self.on["database"].relation_broken, self.on_database_broken
        )
        self._stored.set_default(
            grafana_pebble_ready=False,
            grafana_started=False,
        )
        self.datastore.set_default(database=dict())  # db configuration

    def on_database_changed(self, event):
        """Sets configuration information for database connection."""
        if not self.unit.is_leader():
            return

        if event.unit is None:
            logger.warning("event unit can't be None when setting db config.")
            return

        # save the necessary configuration of this database connection
        database_fields = {
            field: event.relation.data[event.unit].get(field)
            for field in REQUIRED_DATABASE_FIELDS
        }

        # if any required fields are missing, warn the user and return
        missing_fields = [
            field
            for field in REQUIRED_DATABASE_FIELDS
            if database_fields.get(field) is None
        ]
        if len(missing_fields) > 0:
            logger.error(
                "Missing required data fields for related database "
                "relation: {}".format(missing_fields)
            )
            return

        # check if the passed database type is not in VALID_DATABASE_TYPES
        if database_fields["type"] not in VALID_DATABASE_TYPES:
            logger.error(
                "Grafana can only accept databases of the following "
                "types: {}".format(VALID_DATABASE_TYPES)
            )
            return

        # add the new database relation data to the datastore
        self.datastore.database.update(
            {
                field: value
                for field, value in database_fields.items()
                if value is not None
            }
        )

    def on_database_broken(self, _):
        """Removes database connection info from datastore.

        We are guaranteed to only have one DB connection, so clearing
        datastore.database is all we need for the change to be propagated
        to the pod spec."""
        if not self.unit.is_leader():
            return

        # remove the existing database info from datastore
        self.datastore.database = dict()

    def _on_grafana_pebble_ready(self, event):
        logger.info("_on_grafana_pebble_ready")
        self._stored.grafana_pebble_ready = True
        self._start_grafana()

    def _database_config_dict(self):
        db_config = config.get("database", {})

        layer = {
            'summary': 'grafana layer',
            'description': 'grafana layer',
            'services': {
                'grafana': {
                    'override': 'merge',
                    'environment': {
                        'DATABASE_TYPE': db_config.get("type"),
                        'DATABASE_HOST': db_config.get("host"),
                        'DATABASE_NAME': db_config.get("name"),
                        'DATABASE_USER': db_config.get("user"),
                        'DATABASE_PASSWORD': db_config.get("password"),
                        'DATABASE_URL': "{0}://{3}:{4}@{1}/{2}".format(
                            db_config.get("type"),
                            db_config.get("host"),
                            db_config.get("name"),
                            db_config.get("user"),
                            db_config.get("password"))
                    }
                }
            }}
        container = self.unit.containers["grafana"]
        container.add_layer("grafana", layer)

        container.stop()
        container.start()

    def _grafana_layer(self):
        config = self.model.config

        layer = {
            'summary': 'grafana layer',
            'description': 'grafana layer',
            'services': {
                'grafana': {
                    'override': 'replace',
                    'summary': 'grafana service',
                    'command': 'grafana',
                    'default': 'start',
                    'environment': {
                        'HTTP_PORT': config["port"],
                        'LOG_LEVEL': config["grafana_log_level"]
                    }
                }
            }}

        return layer

    def _start_grafana(self):
        logger.info("_start_grafana")
        if self._stored.grafana_started:
            logger.info("grafana already started")
            return
        container = self.unit.containers["grafana"]
        container.add_layer(
            "grafana",
            self._grafana_layer()
        )
        container.autostart()
        self.unit.status = ActiveStatus("grafana started")
        self._stored.grafana_started = True


if __name__ == "__main__":
    main(GrafanaOperator)
