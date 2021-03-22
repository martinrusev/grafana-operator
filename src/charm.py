#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import logging

from ops.charm import CharmBase
from ops.main import main
from ops.framework import StoredState
from ops.model import ActiveStatus


logger = logging.getLogger(__name__)


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
            self.on.grafana_workload_ready, self._on_grafana_workload_ready
        )
        self._stored.set_default(
            grafana_workload_ready=False,
            grafana_started=False,
        )

    def _on_grafana_workload_ready(self, event):
        logger.info("_on_grafana_workload_ready")
        self._stored.grafana_workload_ready = True
        self._start_grafana()

    def _grafana_layer(self):
        layer = {
            'summary': 'grafana layer',
            'description': 'grafana layer',
            'services': {
                'grafana': {
                    'override': 'replace',
                    'summary': 'grafana service',
                    'command': 'grafana',
                    'default': 'start'
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
