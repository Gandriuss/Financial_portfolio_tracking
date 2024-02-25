import functions as f
from config import DATABASE_URI, BASE_DIRECTORY, TOKEN, CHAT_ID
import pandas as pd
import shutil
import os
from datetime import datetime, timedelta
from sqlalchemy import create_engine
import asyncio




# Create the engine to connect to the PostgreSQL database
engine = create_engine(DATABASE_URI)


# Check for an excel file in local directory and read it:
file_name = 'changes_in_portfolio.xlsx'
portfolio_changes = f.portfolio_changes_etl_excel(file_name, BASE_DIRECTORY)


# Connect to database:
with engine.connect() as connection:
    # Start transaction
    with connection.begin() as transaction:                  
        try:

            # Gather last runtime date:
            last_runtime = str(connection.execute(f.sql_last_runtime).fetchone()[0])
            last_runtime = datetime.strptime(last_runtime, '%Y-%m-%d').date()
            #last_runtime = datetime.strptime('2024-02-20', '%Y-%m-%d').date()

            # If latest day not executed, collect new data and place it into a staging table:
            if last_runtime + timedelta(days=1) < datetime.now().date():

                # Look for changes in portfolio:
                if not portfolio_changes.empty:
                    f.process_portfolio_changes(file_name, BASE_DIRECTORY, portfolio_changes, engine, connection, f.sql_active_stocks)     
                    print(portfolio_changes)  
            

                # Gather currently purchased stock details
                active_stocks = pd.read_sql_query(f.sql_active_stocks, engine)

                # Pull updates and insert them into staging table in postgres
                new_stock_info_df = f.get_stock_info(active_stocks, last_runtime)
                new_stock_info_df.to_sql('new_data_stg', con=engine, if_exists='replace', index=False, method='multi')


                # Insert new data into portfolio history:
                connection.execute(f.sql_insert_history)

                # # Update active stock values:
                connection.execute(f.sql_update_stock_price)

                # Commit the transaction
                transaction.commit()


                # Important notification triggers:
                trigger_messages = f.important_triggers(engine)


                # Plot portfolio reports:
                visual_reports_dir = BASE_DIRECTORY + 'visual_reports'
                shutil.rmtree(visual_reports_dir)   # delete outdated graphs
                os.makedirs(visual_reports_dir)
                f.plot_total_value(engine, visual_reports_dir)
                f.plot_combined_profits(engine, visual_reports_dir)
                f.plot_stock_growth(engine, visual_reports_dir)



                # Send updates to a telegram chat:
                asyncio.run(f.telegram_send_updates(engine, TOKEN, CHAT_ID, visual_reports_dir, trigger_messages))

            else:
                print("Newest available data has been already processed")


        except:
            transaction.rollback()
            raise Exception()
        

