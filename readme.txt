main.py:

* process uploads stock information into a local Postgress database within interval [last_run_time;today-1day], looking for currently owned instrument 'End price'.
* To run the script - changes_in_portfolio.xlsx and changes_in_portfolio_blank.xlsx need to be present in parent directory.
* Information is stored in these main tables:
	stocks - 'Active'/'Disabled' stock information, identifying each processed unique instrument.
	active_stocks_info - currently owned ('Active') instrument details, displaying all purchased share amounts and their corresponding prices.
	porftolio_history - historacl track_record containing portfolios' price, value and net_profit fluctuations.
* main.py retrieves queries and functions from functions.py & Postgress database connection credentials from config.py.
* updates are sent to a private Telegram channel via Telegram Bot


processes_portfolio_changes:

* all non_empty historacl changes_in_portfolio.xlsx are stored in this directory.


scheduler:

* passive tracking of portfolio investments is done by setting up a task scheduler catered to a Windows machine (should be configured by the user itself).
* .bat file runs the main script if it receives the last_run_date (from a .txt file) less than the local date of the machine.





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
	