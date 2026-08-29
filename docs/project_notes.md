##Start a single monitor
1) Start as the main process.
```
python scripts/run_monitor.py -d testdata/db/dev -m 1
```

2) Start as a separate OS process
Use the test database in testdata/db/dev.
```
python mhub.py -d testdata/db/dev monitor start --monitor-id 1
```

Use default database
```
python mhub.py monitor start --monitor-id 1
```


##Stop all running monitors
```
python3 mhub.py -d testdata/db/dev -l conf/log.yaml monitor stop-all
```



