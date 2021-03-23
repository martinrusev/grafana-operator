# grafana-operator

## Description

This is the Grafana charm for Kubernetes using the Python Operator Framework.

## Usage

```
$ git clone https://github.com/martinrusev/grafana-operator
$ cd grafana-operator

$ sudo snap install charmcraft --beta
$ charmcraft build
Created 'grafana.charm'.


$ juju deploy ./grafana.charm --resource grafana-image=grafana/grafana:7.4.5

$ juju status                                                                                                                                                                                    canonical-grafana-charm
Model    Controller  Cloud/Region        Version  SLA          Timestamp
grafana  pebble      microk8s/localhost  2.9-rc7  unsupported  16:36:06+01:00

App      Version  Status  Scale  Charm    Store  Channel  Rev  OS      Address  Message
grafana           active      1  grafana  local             9  ubuntu           grafana started

Unit        Workload  Agent  Address       Ports  Message
grafana/0*  active    idle   10.1.243.208         grafana started

```

Visit that IP address at port 3000 in your browser and you should see the Grafana web UI. For example, http://10.1.243.208:3000/

Next, we need to add a database:

```
juju deploy cs:~charmed-osm/mariadb-k8s-35

```

## Developing

Create and activate a virtualenv with the development requirements:

```
    virtualenv -p python3 venv
    source venv/bin/activate
    pip install -r requirements-dev.txt
```

## Testing

The Python operator framework includes a very nice harness for testing
operator behaviour without full deployment. Just `run_tests`:

    ./run_tests
