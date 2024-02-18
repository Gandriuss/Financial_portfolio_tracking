import functions as f
from config import DATABASE_URI, BASE_DIRECTORY
import pandas as pd
import shutil
import os
from datetime import datetime, timedelta
from sqlalchemy import create_engine
import asyncio




# Create the engine to connect to the PostgreSQL database
engine = create_engine(DATABASE_URI)


# Check for an excel file in local directory and read it:
file_name = file_name = BASE_DIRECTORY + 'changes_in_portfolio.xlsx'
portfolio_changes = f.portfolio_changes_etl_excel(file_name)


# Connect to database:
with engine.connect() as connection:
    # Start transaction
    with connection.begin() as transaction:                  
        try:

            # Gather last runtime date:
            last_runtime = str(connection.execute(f.sql_last_runtime).fetchone()[0])
            last_runtime = datetime.strptime(last_runtime, '%Y-%m-%d').date()
            #last_runtime = datetime.strptime('2024-01-03', '%Y-%m-%d').date()

            # If latest day not executed, collect new data and place it into a staging table:
            if last_runtime + timedelta(days=1) < datetime.now().date():

                # Look for changes in portfolio:
                if not portfolio_changes.empty:
                    f.process_portfolio_changes(file_name, portfolio_changes, engine, connection, f.sql_active_stocks)     
                    print(portfolio_changes)  
            

                # Gather currently purchased stock details
                active_stocks = pd.read_sql_query(f.sql_active_stocks, engine)

                # Pull updates and insert them into staging table in postgres
                new_stock_info_df = f.get_stock_info(active_stocks, last_runtime)
                new_stock_info_df.to_sql('new_data_stg', con=engine, if_exists='replace', index=False, method='multi')


                # # Insert new data into portfolio history:
                connection.execute(f.sql_insert_history)

                # # Update active stock values:
                connection.execute(f.sql_update_stock_price)

                # Commit the transaction
                transaction.commit()


                # Plot portfolio reports:
                shutil.rmtree(BASE_DIRECTORY + 'visual_reports')   # delete outdated graphs
                os.makedirs(BASE_DIRECTORY + 'visual_reports')
                f.plot_total_value(engine)
                f.plot_combined_profits(engine)
                f.plot_stock_growth(engine)


                # Send updates to a telegram chat:
                asyncio.run(f.telegram_send_updates(engine))

            else:
                print("Newest available data has been already processed")


        except:
            transaction.rollback()
            raise Exception()
        

