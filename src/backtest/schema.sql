PRAGMA foreign_keys=ON;
CREATE TABLE run_info(run_id TEXT PRIMARY KEY, strategy TEXT NOT NULL, config TEXT NOT NULL,
 signature TEXT NOT NULL, snapshot_sha256 TEXT NOT NULL, settings TEXT NOT NULL, status TEXT NOT NULL,
 report_status TEXT NOT NULL DEFAULT 'pending', report_file TEXT, report_scenario TEXT, reported_at TEXT, error TEXT);
CREATE TABLE daily_account(trade_date TEXT PRIMARY KEY, cash TEXT NOT NULL, positions_value TEXT,
 equity TEXT, valuation_status TEXT NOT NULL, strategy_state TEXT NOT NULL);
CREATE TABLE daily_positions(trade_date TEXT REFERENCES daily_account DEFERRABLE INITIALLY DEFERRED,
 ts_code TEXT, security_id TEXT NOT NULL, shares INTEGER NOT NULL CHECK(shares>0), sellable INTEGER NOT NULL,
 close TEXT, price_date TEXT, market_value TEXT,
 tags TEXT NOT NULL, tags_unknown TEXT NOT NULL, status_reason TEXT NOT NULL,
 PRIMARY KEY(trade_date,ts_code));
CREATE TABLE position_lots(id INTEGER PRIMARY KEY, ts_code TEXT, security_id TEXT, bought TEXT, shares INTEGER CHECK(shares>0));
CREATE TABLE orders(id INTEGER PRIMARY KEY, created TEXT NOT NULL, phase TEXT, target TEXT, session TEXT,
 ts_code TEXT, security_id TEXT, side TEXT, lots INTEGER, touch_low TEXT, status TEXT, reason TEXT);
CREATE INDEX due_orders ON orders(target,session,status);
CREATE TABLE fills(id INTEGER PRIMARY KEY, order_id INTEGER UNIQUE REFERENCES orders, trade_date TEXT, session TEXT,
 ts_code TEXT, side TEXT, shares INTEGER CHECK(shares>0), price TEXT, amount TEXT);
CREATE TABLE cash_ledger(id INTEGER PRIMARY KEY, trade_date TEXT, order_id INTEGER REFERENCES orders, delta TEXT NOT NULL);
CREATE TABLE metric_scenarios(scenario_id TEXT PRIMARY KEY, config TEXT NOT NULL);
CREATE TABLE scenario_daily_inputs(scenario_id TEXT REFERENCES metric_scenarios, trade_date TEXT REFERENCES daily_account,
 rf_return REAL, benchmark_return REAL, benchmark_close REAL, PRIMARY KEY(scenario_id,trade_date));
CREATE TABLE metric_definitions(name TEXT PRIMARY KEY,label TEXT NOT NULL,unit TEXT,version TEXT);
CREATE TABLE daily_metrics(scenario_id TEXT REFERENCES metric_scenarios,trade_date TEXT REFERENCES daily_account,
 metric_name TEXT REFERENCES metric_definitions,value REAL, reason TEXT, samples INTEGER, details TEXT,
 PRIMARY KEY(scenario_id,trade_date,metric_name));
CREATE INDEX metric_series ON daily_metrics(scenario_id,metric_name,trade_date);
CREATE TABLE data_definitions(key TEXT PRIMARY KEY,scope TEXT,kind TEXT,unit TEXT,version TEXT);
CREATE TABLE strategy_data(trade_date TEXT REFERENCES daily_account DEFERRABLE INITIALLY DEFERRED,
 key TEXT REFERENCES data_definitions, ts_code TEXT NOT NULL DEFAULT '', value,
 PRIMARY KEY(trade_date,key,ts_code));
CREATE VIEW strategy_daily_data AS SELECT d.* FROM strategy_data d JOIN data_definitions USING(key) WHERE scope='daily';
CREATE VIEW strategy_position_data AS SELECT d.* FROM strategy_data d JOIN data_definitions USING(key) WHERE scope='position';
CREATE VIEW strategy_run_data AS SELECT d.* FROM strategy_data d WHERE key IN (SELECT key FROM data_definitions WHERE scope='run')
 AND trade_date=(SELECT max(x.trade_date) FROM strategy_data x WHERE x.key=d.key);
CREATE TABLE events(id INTEGER PRIMARY KEY,trade_date TEXT,kind TEXT,message TEXT);
CREATE TABLE metric_checkpoints(scenario_id TEXT PRIMARY KEY REFERENCES metric_scenarios, state TEXT NOT NULL);
