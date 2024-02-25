main.py:

	* process uploads stock information into a local Postgress database within interval [last_run_time;today-1day], looking for currently owned instrument 'End price'.
	* to run the script - changes_in_portfolio.xlsx and changes_in_portfolio_blank.xlsx need to be present in parent directory.
	* information is stored in these main tables:
		stocks - 'Active'/'Disabled' stock information, identifying each processed unique instrument.
		active_stocks_info - currently owned ('Active') instrument details, displaying all purchased share amounts and their corresponding prices.
		porftolio_history - historacl track_record containing portfolios' price, value and net_profit fluctuations.
	* main.py retrieves queries and functions from functions.py & Postgress database connection credentials from config.py.
	* updates are sent to a private Telegram channel via Telegram Bot

functions.py
	* set event triggers at a point of interest by adding code blocks to 'important_triggers' function:
	 	Query database for relevant information & add notification messages to 'message_list' that will be sent to telegram after the process completes.

config.py
	* stores database credentials, project root (base) directory & Telegrams API connections

processes_portfolio_changes:

* all non_empty historacl changes_in_portfolio.xlsx are stored in this directory.


scheduler:

* passive tracking of portfolio investments is done by setting up a task scheduler catered to a Windows machine (should be configured by the user itself).
* .bat file runs the main script if it receives the last_run_date (from a .txt file) less than the local date of the machine.



===============================================================
Postgress tables:

CREATE TABLE stocks
(
    id SERIAL PRIMARY KEY,
    name VARCHAR(200),
    ticker VARCHAR(200),
    price REAL,
    share REAL,
    color VARCHAR(200),
    st VARCHAR(200)
)

CREATE TABLE active_stocks_info
(
    id INTEGER,
    name VARCHAR(200),
    ticker VARCHAR(200),
    price REAL,
    share REAL,
    dt DATE
)

CREATE TABLE portfolio_history        
(
    id INTEGER,
    name VARCHAR(200),
    ticker VARCHAR(200),
    end_price REAL,
    shares REAL,
    value REAL,
    invested REAL,
    profit REAL,
    dt DATE
)

CREATE TABLE new_data_stg
(
    dt date,
    end_price real,
    stock_name VARCHAR(200),
    ticker VARCHAR(200)
)

CREATE TABLE changes
(
    dt date,
    stock_id integer,
    shares_bought_sold numeric,
    purchase_price numeric
)

CREATE OR REPLACE VIEW portfolio AS
    WITH daily_portfolio AS (
        SELECT
            SUM(profit) AS total_profit,
            SUM(value) AS total_value,
            dt
        FROM portfolio_history
        GROUP BY dt
    ),
    daily_comparative_portfolio AS (
        SELECT *,
               LAG(total_value) OVER(ORDER BY dt) as yesterdays_total,
               LAG(total_value, 7) OVER(ORDER BY dt) as week_ago_total,
               LAG(total_value, 30) OVER(ORDER BY dt) as month_ago_total,
               LAG(total_value, 180) OVER(ORDER BY dt) as _6month_ago_total,
               LAG(total_value, 365) OVER(ORDER BY dt) as year_ago_total
        FROM daily_portfolio
    )
    SELECT
        dcp.dt,
        dcp.total_profit,
        dcp.total_value,
        CASE
            WHEN ch.dt IS NOT NULL THEN 1
        END AS change,
        ROUND(CAST((total_value - yesterdays_total) / yesterdays_total AS numeric), 3) as ch_1D_ago,
        ROUND(CAST((total_value - week_ago_total) / week_ago_total AS numeric), 3) as ch_7D_ago,
        ROUND(CAST((total_value - month_ago_total) / month_ago_total AS numeric), 3) as ch_1M_ago,
        ROUND(CAST((total_value - _6month_ago_total) / _6month_ago_total AS numeric), 3) as ch_6M_ago,
        ROUND(CAST((total_value - year_ago_total) / year_ago_total AS numeric), 3) as ch_1Y_ago
    FROM daily_comparative_portfolio dcp
    LEFT JOIN (SELECT distinct dt FROM changes) ch
        ON ch.dt = dcp.dt
    ORDER BY dcp.dt DESC;


CREATE TABLE colors                   -- color generation script can be found in .ipynb file as a function 'generate_and_store_colors'
(
    color_id int,
    color_name_hex VARCHAR(200)
)

===============================================================



Troubleshooting and input errors:
* main.ipynb containing multiple cells is left as a troubleshooting, testing script.
* In case there is a missing interval in between existing data: 
	you can rerun the script, if no changes to portfolio shares have been made.
* Do not run the script for the interval where an instrument was bought AND sold - script won't take that instrument into account.
* In case false information has been inputed into changes_in_portfolio.xlsx:
	Update 'stocks' table according to the info before the false input
	Update 'active_stocks_info' table according to the info before the false input
	delete from 'porftolio_history' the day of false input and later ones
	delete input from 'changes'.
	
