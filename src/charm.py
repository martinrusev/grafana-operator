#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import base64
import yaml
import json
import uuid

from ops.charm import CharmBase, PebbleReadyEvent
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, ModelError
from ops.pebble import ServiceStatus

logger = logging.getLogger(__name__)


# These are the required and optional relation data fields
# In other words, when relating to this charm, these are the fields
# that will be processed by this charm.
REQUIRED_DATASOURCE_FIELDS = {
    "private-address",  # the hostname/IP of the data source server
    "port",  # the port of the data source server
    "source-type",  # the data source type (e.g. prometheus)
}

OPTIONAL_DATASOURCE_FIELDS = {
    "source-name",  # a human-readable name of the source
}

REQUIRED_DATABASE_FIELDS = {
    "type",  # mysql, postgres or sqlite3 (sqlite3 doesn't work for HA)
    "host",  # in the form '<url_or_ip>:<port>', e.g. 127.0.0.1:3306
    "name",
    "user",
    "password",
}

VALID_DATABASE_TYPES = {"mysql", "postgres", "sqlite3"}


PROVISIONING_PATH = "/etc/grafana/provisioning"

SERVICE = "grafana"


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

        # -- grafana-source relation observations
        self.framework.observe(
            self.on["grafana-source"].relation_changed, self.on_grafana_source_changed
        )
        self.framework.observe(
            self.on["grafana-source"].relation_broken, self.on_grafana_source_broken
        )

        self._stored.set_default(sources=dict())  # available data sources
        self._stored.set_default(source_names=set())  # unique source names
        self._stored.set_default(sources_to_delete=set())
        self._stored.set_default(database=dict())  # db configuration

        # -- actions observations
        self.framework.observe(
            self.on.import_dashboard_action, self.on_import_dashboard_action
        )

        # shortcuts
        self.grafana_container = self.unit.containers[SERVICE]

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
        self._stored.database.update(
            {
                field: value
                for field, value in database_fields.items()
                if value is not None
            }
        )

        self.grafana_container.add_layer("grafana", self._database_layer, True)
        self._restart_grafana()

    def on_database_broken(self, _):
        """Removes database connection info from datastore.
        We are guaranteed to only have one DB connection, so clearing
        datastore.database is all we need for the change to be propagated
        to the pod spec."""
        if not self.unit.is_leader():
            return

        # remove the existing database info from datastore
        self._stored.database = dict()

        # TODO - Update Pebble - stop the service, remove the DB credentials?

    def on_grafana_source_changed(self, event):
        """Get relation data for Grafana source.

        This event handler (if the unit is the leader) will get data for
        an incoming grafana-source relation and make the relation data
        is available in the app's datastore object (StoredState).
        """
        # if this unit is the leader, set the required data
        # of the grafana-source in this charm's datastore
        if not self.unit.is_leader():
            return

        # if there is no available unit, remove data-source info if it exists
        if event.unit is None:
            logger.warning("event unit can't be None when setting data sources.")
            return

        # dictionary of all the required/optional datasource field values
        # using this as a more generic way of getting data source fields
        datasource_fields = {
            field: event.relation.data[event.unit].get(field)
            for field in REQUIRED_DATASOURCE_FIELDS | OPTIONAL_DATASOURCE_FIELDS
        }

        missing_fields = [
            field
            for field in REQUIRED_DATASOURCE_FIELDS
            if datasource_fields.get(field) is None
        ]

        # check the relation data for missing required fields
        if len(missing_fields) > 0:
            logger.error(
                "Missing required data fields for grafana-source "
                "relation: {}".format(missing_fields)
            )
            self._remove_source_from_datastore(event.relation.id)
            return

        # specifically handle optional fields if necessary
        # check if source-name was not passed or if we have already saved the provided name
        if (
            datasource_fields["source-name"] is None
            or datasource_fields["source-name"] in self._stored.source_names
        ):
            default_source_name = "{}_{}".format(event.app.name, event.relation.id)
            logger.warning(
                "No name 'grafana-source' or provided name is already in use. "
                "Using safe default: {}.".format(default_source_name)
            )
            datasource_fields["source-name"] = default_source_name

        self._stored.source_names.add(datasource_fields["source-name"])

        # set the first grafana-source as the default (needed for pod config)
        # if `self._stored.sources` is currently empty, this is the first
        datasource_fields["isDefault"] = "false"
        if not dict(self._stored.sources):
            datasource_fields["isDefault"] = "true"

        # add unit name so the source can be removed might be a
        # duplicate of 'source-name', but this will guarantee lookup
        datasource_fields["unit_name"] = event.unit.name

        # add the new datasource relation data to the current state
        new_source_data = {
            field: value
            for field, value in datasource_fields.items()
            if value is not None
        }
        self._stored.sources.update({event.relation.id: new_source_data})

        self._generate_datasource_config()
        self._restart_grafana(event)

    def on_grafana_source_broken(self, event):
        """When a grafana-source is removed, delete from the datastore."""
        if self.unit.is_leader():
            self._remove_source_from_datastore(event.relation.id)

        self._generate_datasource_config()
        self._restart_grafana(event)

    def _remove_source_from_datastore(self, rel_id):
        """Remove the grafana-source from the datastore."""

        logger.info("Removing all data for relation: {}".format(rel_id))
        removed_source = self._stored.sources.pop(rel_id, None)
        if removed_source is None:
            logger.warning("Could not remove source for relation: {}".format(rel_id))
        else:
            self._stored.source_names.remove(removed_source["source-name"])
            self._stored.sources_to_delete.add(removed_source["source-name"])

    def _generate_datasource_config(self):
        datasources_dict = {"apiVersion": 1, "datasources": [], "deleteDatasources": []}

        for _, source_info in self._stored.sources.items():
            source = {
                "orgId": "1",
                "access": "proxy",
                "isDefault": source_info["isDefault"],
                "name": source_info["source-name"],
                "type": source_info["source-type"],
                "url": "http://{}:{}".format(
                    source_info["private-address"], source_info["port"]
                ),
            }
            datasources_dict["datasources"].append(source)

        for name in self._stored.sources_to_delete:
            source = {"orgId": 1, "name": name}
            datasources_dict["deleteDatasources"].append(source)

        # Grafana automatically and recursively reads all YAML files from /etc/grafana/provisioning
        datasources_yaml = os.path.join(
            PROVISIONING_PATH, "datasources", "datasources.yaml"
        )
        with open(datasources_yaml, "w+") as file:
            yaml.dump(datasources_dict, file)

    def _restart_grafana(self, event):
        container = event.workload
        container.stop_services([SERVICE])
        container.start_services([SERVICE])

    def _on_grafana_pebble_ready(self, event: PebbleReadyEvent) -> None:
        container = event.workload
        logger.info("_on_grafana_pebble_ready")

        # Check we can get a list of services back from the Pebble API
        if self._is_running(container, "grafana"):
            logger.info("grafana already started")
            return

        self._generate_datasource_config()

        logger.info("_start_grafana")
        container.add_layer("grafana", self._grafana_layer(), True)
        container.autostart()
        self.unit.status = ActiveStatus("grafana started")

    def on_import_dashboard_action(self, event):
        dasbhoard_base64_string = event.params["dashboard"]

        name = "{}.json".format(uuid.uuid4())

        dashboard_path = os.path.join(PROVISIONING_PATH, "dashboards", name)
        with open(dashboard_path, "w+") as file:
            dashboard_bytes = base64.b64decode(dasbhoard_base64_string).decode("ascii")
            dashboard_string = dashboard_bytes
            json.dump(dashboard_string, file)

        self._restart_grafana(event)

    def _database_layer(self):
        db_config = self.model.config.get("database", {})

        layer = {
            "summary": "grafana layer",
            "description": "grafana layer",
            "services": {
                "grafana": {
                    "override": "merge",
                    "environment": {
                        "GF_DATABASE_TYPE": db_config.get("type"),
                        "GF_DATABASE_HOST": db_config.get("host"),
                        "GF_DATABASE_NAME": db_config.get("name"),
                        "GF_DATABASE_USER": db_config.get("user"),
                        "GF_DATABASE_PASSWORD": db_config.get("password"),
                        "GF_DATABASE_URL": "{0}://{3}:{4}@{1}/{2}".format(
                            db_config.get("type"),
                            db_config.get("host"),
                            db_config.get("name"),
                            db_config.get("user"),
                            db_config.get("password"),
                        ),
                    },
                }
            },
        }

        return layer

    def _grafana_layer(self):
        config = self.model.config

        layer = {
            "summary": "grafana layer",
            "description": "grafana layer",
            "services": {
                "grafana": {
                    "override": "replace",
                    "summary": "grafana service",
                    "command": "grafana-server",
                    # TODO - fix this once this charm is migrated to juju 2.9-rc8
                    # "startup": "enabled",
                    "default": "start",
                    "environment": [
                        {"GF_HTTP_PORT": config["port"]},
                        {"GF_LOG_LEVEL": config["grafana_log_level"]},
                        {"GF_PATHS_PROVISIONING": PROVISIONING_PATH},
                    ],
                }
            },
        }

        return layer

    def _is_running(self, container, service):
        """Helper method to determine if a given service is running in a given container"""
        try:
            service = container.get_service(service)
        except ModelError:
            return False
        return service.current == ServiceStatus.ACTIVE


if __name__ == "__main__":
    main(GrafanaOperator)
