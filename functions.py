import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import to_hex
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from itertools import product
import shutil
import os
import time
from telegram import Bot, InputMediaPhoto
import asyncio




####################################################################################### 
####################### RETRIEVING DATA FROM YAHOO AND EXCEL: #########################
####################################################################################### 


def convert_shares(value):
    if value == 'all':
        return 0
    try:
        return float(value)
    except ValueError:
        return None 


def portfolio_changes_etl_excel(file_name, base_directory):
    portfolio_changes = pd.read_excel(base_directory+file_name, header=0)
    if portfolio_changes.empty or not portfolio_changes.replace('', np.nan).isnull().any().any():
        portfolio_changes['price'] = pd.to_numeric(portfolio_changes['price'], errors='coerce')
        portfolio_changes['share'] = portfolio_changes['share'].apply(convert_shares)
        portfolio_changes['date'] = pd.to_datetime(portfolio_changes['date']).dt.date
        portfolio_changes.rename(columns={'date': 'dt'}, inplace=True)
        portfolio_changes.sort_values(by='dt', ascending=True, inplace=True)

        return portfolio_changes

    else:
        raise ValueError("There are empty values in the updates file") 



def get_stock_info(active_stocks, last_day):

    # Calculate runtime days & intervals
    next_day = last_day + timedelta(days=1)         
    end_date = datetime.now().date() 
    update_dates = pd.date_range(start=next_day, end=end_date - timedelta(days=1)).to_pydatetime().tolist()  # updates for end_price only have info up to: today - 1 day
    update_dates = [d.date() for d in update_dates]


    print(f"Updating dates: [{next_day};{end_date - timedelta(days=1)}]")
    print(f"Search dates: [{last_day};{end_date})")


    # Get active stock tickers:
    tickers = active_stocks['ticker'].tolist()

    all_stocks_df = pd.DataFrame()

    for ticker in tickers:
        stock = yf.Ticker(ticker)
        # Get historical market data

        hist = stock.history(period="1d", start=last_day, end=end_date)                  # dates retrieved: [start; end). Interval lenght has to be > 1
        if not hist.empty:
            # Reset index to turn the Date index into a column
            hist.reset_index(inplace=True)

            # Convert 'Date' to datetime format
            hist['Date'] = pd.to_datetime(hist['Date']).dt.date
            hist['ticker'] = ticker 

            # Keep only the required columns
            hist = hist[['Date', 'Close', 'ticker']]
            hist.rename(columns={'Close': 'end_price'}, inplace=True)
            hist.rename(columns={'Date': 'dt'}, inplace=True)

            # Append this data to the main DataFrame
            all_stocks_df = pd.concat([all_stocks_df, hist])

        else:                                                      
                    
            # If there are no new of stock value
            missing_data = pd.DataFrame({
                'dt': [next_day],
                'end_price': [None],
                'ticker': [ticker]
            })

            all_stocks_df = pd.concat([all_stocks_df, missing_data])

    # Reset the index of the final DataFrame
    all_stocks_df.reset_index(drop=True, inplace=True)

    # Combine all dates with all tickers and add new & known info
    all_dates_df = pd.DataFrame(list(product(tickers, update_dates)), columns=['ticker', 'dt'])
    all_dates_and_named_df = all_dates_df.merge(active_stocks[['ticker','name']], on=['ticker'], how='left')
    all_dates_and_updates = all_dates_and_named_df.merge(all_stocks_df, on=['ticker', 'dt'], how='left')


    # For each ticker, fill the earliest date's missing price with the current price
    for ticker in tickers:
        current_price = active_stocks[active_stocks['ticker'] == ticker]['price'].iloc[0]
        earliest_date_mask = (all_dates_and_updates['ticker'] == ticker) & \
                             (all_dates_and_updates['dt'] == all_dates_and_updates['dt'].min())
        all_dates_and_updates.loc[earliest_date_mask & all_dates_and_updates['end_price'].isna(), 'end_price'] = current_price


    # Forward fill missing ticker prices
    all_dates_and_updates['end_price'] = all_dates_and_updates.groupby('ticker')['end_price'].ffill().bfill()


    return all_dates_and_updates


def process_portfolio_changes(file_name, base_directory, portfolio_changes, engine, connection, sql_active_stocks):   

    for index, row in portfolio_changes.iterrows():             

        active_stocks = pd.read_sql_query(sql_active_stocks, engine)
        active_tickers = active_stocks['ticker'].tolist()

        instrument = pd.DataFrame([row], columns=['name', 'ticker', 'price', 'share', 'dt'])
        
        if instrument['share'].iloc[0] > 0:

            # Check if "stocks" ticker is between stocks WHERE st = 'Active'
            if instrument['ticker'].iloc[0] in active_tickers:
                # Insert stocks name, stocks ticker, stocks purchase price & date into "active_stock_info" & into "stocks"
                active_stock_id = active_stocks[active_stocks['ticker'] == instrument['ticker'].iloc[0]]['id'].iloc[0]
                instrument['id'] = active_stock_id
                sql_update_share_price = text(f'''
                                                UPDATE stocks
                                                SET
                                                    share = share + {instrument['share'].iloc[0]}
                                                WHERE id = {instrument['id'].iloc[0]} 
                                            ''')
                connection.execute(sql_update_share_price)
                # Insert stocks name, stocks ticker, stocks purchase price & date into "active_stock_info"
                instrument.to_sql('active_stocks_info', con=engine, if_exists='append', index=False, method='multi')

            else:
                # Insert stocks name, stocks ticker & set stocks purchase price as price and set st = 'Active' in table "stocks"
                instrument['st'] = 'Active'
                instrument['color_id'] = color_to_new_stock(engine)
                instrument[['name', 'ticker', 'price', 'share', 'color_id', 'st']].to_sql('stocks', con=engine, if_exists='append', index=False, method='multi')
                # Insert stocks name, stocks ticker, stocks purchase price & date into "active_stock_info"
                sql_find_max_id = text('''SELECT MAX(id) FROM stocks''')
                new_max_id = pd.read_sql_query(sql_find_max_id, engine).iloc[0, 0]
                instrument['id'] = new_max_id
                instrument[['id', 'name', 'ticker', 'price', 'share', 'dt']].to_sql('active_stocks_info', con=engine, if_exists='append', index=False, method='multi')


        elif instrument['share'].iloc[0] < 0 or instrument['share'].iloc[0] == 0:    # sell all shares <==> share = 0
            
            # Check if "stocks" ticker is between stocks WHERE st = 'Active'
            if instrument['ticker'].iloc[0] in active_tickers:

                active_stock_id = active_stocks[active_stocks['ticker'] == instrument['ticker'].iloc[0]]['id'].iloc[0]
                instrument['id'] = active_stock_id

                if instrument['share'].iloc[0] == 0:
                    # If share = 'all' then remove all records active records
                    sql_delete_share_stocks = text(f'''
                                                    UPDATE stocks
                                                    SET
                                                        st = 'Disabled',
                                                        share = 0
                                                    WHERE 
                                                        ticker = '{instrument['ticker'].iloc[0]}'
                                                        AND st = 'Active'
                                                ''')
                    connection.execute(sql_delete_share_stocks) 
                    sql_delete_share_active_stocks_info = text(f'''
                                                    DELETE FROM active_stocks_info WHERE ticker = '{instrument['ticker'].iloc[0]}'
                                                ''')
                    connection.execute(sql_delete_share_active_stocks_info) 
                
                else:
                    # Use first in first out algorithm to update stock records for that ticker in "active_stocks_info"
                    shares_to_sell = abs(instrument['share'].iloc[0])
                    sales_ticker = instrument['ticker'].iloc[0]

                    # Fetch all active stock info for the ticker
                    active_records = pd.read_sql_query(
                        f"SELECT * FROM active_stocks_info WHERE ticker = '{sales_ticker}' ORDER BY dt ASC",
                        engine
                    )

                    # Perform FIFO on the DataFrame
                    for index, record in active_records.iterrows():
                        if shares_to_sell <= 0:
                            break  # All shares have been sold

                        shares_in_record = record['share']
                        if shares_to_sell > shares_in_record:
                            # All shares in this record are sold
                            shares_to_sell -= shares_in_record
                            active_records.at[index, 'share'] = 0
                        else:
                            # Only some shares in this record are sold
                            active_records.at[index, 'share'] -= shares_to_sell
                            shares_to_sell = 0

                    # Delete old records from the database for this ticker                             
                    connection.execute(f"DELETE FROM active_stocks_info WHERE ticker = '{sales_ticker}'")


                    # Filter out records with 0 shares as they are considered sold
                    active_records = active_records[active_records['share'] > 0]

                    # Insert updated records back into the database
                    active_records.to_sql('active_stocks_info', con=engine, if_exists='append', index=False, method='multi')

                    # Update the 'stocks' table with the new total number of shares
                    if active_records['share'].sum() == 0:
                        connection.execute(
                            f"UPDATE stocks SET st = 'Disabled', share = 0 WHERE ticker = '{sales_ticker}' AND st ='Active'"
                        ) 
                    else:
                        connection.execute(
                            f"UPDATE stocks SET share = {active_records['share'].sum()} WHERE ticker = '{sales_ticker}' AND st = 'Active'"
                        )                                

            else:
                raise ValueError(f"Instrument not found: {instrument['ticker'].iloc[0]}")

        # Insert stocks name, stocks ticker, stocks purchase price & date into "changes"
        instrument[['stock_id', 'shares_bought_sold', 'purchase_price']] = instrument[['id', 'share', 'price']]
        instrument[['dt', 'stock_id', 'shares_bought_sold', 'purchase_price']].to_sql('changes', con=engine, if_exists='append', index=False, method='multi')

    # Move excel file the to a folder named "processed" with a changed, parametrized name:

    processed_dir = 'processed_portfolio_changes'
    # Check if the directory exists, if not, create it
    if not os.path.exists(processed_dir):
        os.makedirs(processed_dir)

    new_filename = f"processed_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file_name}"

    # Construct the new file path
    new_file_path = os.path.join(processed_dir, new_filename)

    # Move the file
    shutil.move(file_name, new_file_path)

    print(f"File moved to {new_file_path}") 

    # Make another empty portfolio changes file for the future: 
    original_file = base_directory +'changes_in_portfolio_blank.xlsx'
    new_file = base_directory + 'changes_in_portfolio.xlsx'
    # Copy the file
    shutil.copy(original_file, new_file)

    print(f"File copied successfully: {new_file}")



####################################################################################### 
############################################ SQL STATEMENTS FOR MAIN: #################
####################################################################################### 

# Prepare the SQL statement with parameters
sql_active_stocks = text('''
                SELECT * FROM stocks
                WHERE st = 'Active';''')

sql_last_runtime = text('''
                SELECT MAX(dt) FROM portfolio_history''')

sql_update_stock_price = text('''
                WITH latest_prices AS 
                (
                    SELECT
                        ticker,
                        end_price,
                        ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY dt DESC) AS rn
                    FROM new_data_stg  
                )
                UPDATE stocks
                SET price = latest_prices.end_price
                FROM latest_prices
                WHERE
                    stocks.ticker = latest_prices.ticker AND latest_prices.rn = 1;''')  

sql_insert_history = text('''
                INSERT INTO portfolio_history
                WITH sum_of_shares_and_investments AS
                (
                    SELECT
                        s.id,
                        new.ticker,
                        new.name,
                        new.end_price,
                        sum(asi.share) AS shares_owned,
                        sum(asi.share*asi.price) AS invested,
                        new.dt
                    FROM new_data_stg new
                    LEFT JOIN active_stocks_info asi
                        ON asi.ticker = new.ticker
                        AND asi.dt <= new.dt               -- only join on data that has been accumulated
                    LEFT JOIN stocks s
                        ON asi.ticker = s.ticker           -- ensure having all ids
                    WHERE s.st = 'Active'
                    GROUP BY s.id,new.ticker,new.name,new.end_price,new.dt
                )
                SELECT
                    id,
                    name,
                    ticker,
                    end_price,
                    shares_owned,
                    (end_price*shares_owned) as value,
                    invested,
                    (end_price*shares_owned - invested) as profit,
                    dt
                FROM sum_of_shares_and_investments
                WHERE dt NOT IN (SELECT dt FROM portfolio_history)''')


sql_insert_profit_tracker_history = text('''
                INSERT INTO profit_tracker
                SELECT
                    dt,
                    total_days_profit,
                    id,
                    profit,
                    value,
                    invested
                FROM current_profit_view''')



####################################################################################### 
############################################ FOR PLOTTING: ############################
####################################################################################### 


def color_to_new_stock(engine):
    with engine.connect() as conn:
        # Fetch currently active and disabled stocks with their colors
        disabled_colors_query = "SELECT id, color_id FROM stocks WHERE st = 'Disabled' ORDER BY id"
        never_used_colors_query = '''SELECT color_id
                                     FROM colors
                                     WHERE color_id NOT IN (SELECT color_id FROM stocks)
                                   '''
        
        disabled_colors_df = pd.read_sql_query(disabled_colors_query, conn)
        never_used_colors_df = pd.read_sql_query(never_used_colors_query, conn)

        # Check if any unused colors are available
        unused_colors = [color for color in never_used_colors_df['color_id']]

        # Assign color to the new stock
        if unused_colors:
            new_color = unused_colors[0]
        else:
            # If no unused colors, take color from disabled stock with lowest id
            new_color = disabled_colors_df.iloc[0]['color_id'] if not disabled_colors_df.empty else 'grey'

        return new_color  # Return the new color
    

def plot_total_value(engine, visual_reports_dir):
    # Assuming 'engine' is your SQLAlchemy engine connected to the database
    with engine.connect() as conn:
        # Retrieve all history from portfolio_history
        query = """
                SELECT ph.id, s.name, ph.value, ph.dt, c.color_name_hex
                FROM portfolio_history ph
                JOIN stocks s ON ph.id = s.id
                JOIN colors c ON s.color_id = c.color_id
                ORDER BY s.id ASC
                """
        portfolio_history_df = pd.read_sql(query, conn)
        # Retrieve all change dates from changes
        change_dates_df = pd.read_sql("SELECT DISTINCT dt FROM changes", conn)

    # Extract name and color to plot them when using stocks id:
    color_mapping = dict(zip(portfolio_history_df['id'], portfolio_history_df['color_name_hex']))
    stock_mapping = dict(zip(portfolio_history_df['id'], portfolio_history_df['name']))
    

    # Group by 'dt' and sum 'value' to get the total value per day
    daily_totals = portfolio_history_df.groupby(['dt','id'])['value'].sum().unstack('id').fillna(0)

    
    # Sort the DataFrame by date to ensure correct plotting
    daily_totals.sort_index(ascending=True, inplace=True)

    # Plot the stacked area chart for each name
    fig, ax = plt.subplots(figsize=(15, 5))

    # Initialize a baseline (starting point for the stacking)
    baseline = pd.Series(0, index=daily_totals.index)
    
    # Plot each stock's value over time and color the area under the curve
    for id in daily_totals.columns:
        color = color_mapping[id]
        name = stock_mapping[id]
        ax.fill_between(daily_totals.index, baseline, baseline + daily_totals[id], label=name, color = color)
        baseline += daily_totals[id]

    for change_date in change_dates_df['dt']:
        ax.axvline(x=change_date, color='gray', linestyle=':')

    # Formatting the plot
    ax.legend(loc='upper left')
    ax.set_title('Portfolio Value Over Time')
    ax.set_xlabel('Date')
    ax.set_ylabel('Value')
    plt.xticks(rotation=45)
    plt.tight_layout()  # Adjust the plot to ensure everything fits without overlapping
    

    # Show the plot
    #plt.show()

    # Saving the plot as an image:
    fig.savefig(os.path.join(visual_reports_dir, 'total_portfolio' + '.png'))
    plt.close(fig)  # Close the figure to free memory


def plot_combined_profits(engine, visual_reports_dir):
    with engine.connect() as conn:

        profit_query = """
                SELECT 
                    ph.id, 
                    s.name, 
                    ph.profit, 
                    ph.dt, 
                    c.color_name_hex
                FROM portfolio_history ph
                JOIN stocks s ON ph.id = s.id
                JOIN colors c ON s.color_id = c.color_id
                ORDER BY s.id ASC
                """
        profit_df = pd.read_sql(profit_query, conn)

        # Retrieve all change dates from changes
        change_dates_df = pd.read_sql("SELECT DISTINCT dt FROM changes", conn)

    # Extract color mapping
    color_mapping = dict(zip(profit_df['id'], profit_df['color_name_hex']))
    name_mapping = dict(zip(profit_df['id'], profit_df['name']))

    # Create figure and axis
    fig, ax = plt.subplots(figsize=(15, 5))

    # Group by 'dt' and sum 'profit' to get the total profit per day
    total_profit_series = profit_df.groupby('dt')['profit'].sum()

    # Plot total sum of profits as a black curve
    ax.plot(total_profit_series.index, total_profit_series, label='Total Profit', color='black')

    for change_date in change_dates_df['dt']:
        ax.axvline(x=change_date, color='gray', linestyle=':')

    # Plot positive and negative profits using helper function
    used_labels = set()  # Set to keep track of used labels
    plot_profits(ax, profit_df[profit_df['profit'] > 0], color_mapping, name_mapping, 'Positive Profits', 0, used_labels)
    plot_profits(ax, profit_df[profit_df['profit'] < 0], color_mapping, name_mapping, 'Negative Profits', 0, used_labels)

    # Formatting the plot
    ax.legend(loc='upper left')
    ax.set_title('Portfolio Profits Over Time')
    ax.set_xlabel('Date')
    ax.set_ylabel('Profit (euro)')
    plt.xticks(rotation=45)
    plt.grid(True)
    plt.tight_layout()  # Adjust the plot to ensure everything fits without overlapping

    # Show the plot
    #plt.show()

    # Saving the plot as an image:
    fig.savefig(os.path.join(visual_reports_dir, 'combined_profits' + '.png'))
    plt.close(fig)  # Close the figure to free memory





def plot_profits(ax, profit_df, color_mapping, name_mapping, title, start_baseline, used_labels):
    # Group by 'dt' and 'id' and sum 'profit' to get the total value per day
    daily_totals = profit_df.groupby(['dt', 'id'])['profit'].sum().unstack('id').fillna(0)

    # Sort the DataFrame by date to ensure correct plotting
    daily_totals.sort_index(ascending=True, inplace=True)

    # Initialize a baseline for stacking
    baseline = pd.Series(start_baseline, index=daily_totals.index)

    # Plot each stock's profit over time and color the area under the curve
    for id in daily_totals.columns:
        color = color_mapping[id]
        label = name_mapping[id] if name_mapping[id] not in used_labels else None
        if label:  # If label is not None, add to used_labels set
            used_labels.add(label)
        ax.fill_between(daily_totals.index, baseline, baseline + daily_totals[id], label=label, color=color)
        baseline += daily_totals[id]



def plot_stock_growth(engine, visual_reports_dir):
    with engine.connect() as conn:
        # Retrieve all history from portfolio_history with growth calculated
        query = """
        WITH previous_profits as
        (
            SELECT
                ph.id,
                s.name,
                ph.profit,
                LAG(ph.profit, 1, 0) OVER (PARTITION BY ph.id ORDER BY ph.dt) AS prev_profit,
                ph.dt,
                c.color_name_hex
            FROM portfolio_history ph
            JOIN stocks s ON ph.id = s.id
            JOIN colors c ON s.color_id = c.color_id
        ),
        growth AS
        (
            SELECT
                id,
                name,
                 (profit-prev_profit)
                as growth,
                dt,
                color_name_hex
            FROM previous_profits
        )
        SELECT * FROM growth
        WHERE growth != 0
        ORDER BY id ASC, dt ASC
        """
        growth_df = pd.read_sql(query, conn)

        # Retrieve all change dates from changes
        change_dates_df = pd.read_sql("SELECT DISTINCT dt FROM changes", conn)


    # Extract color mapping
    color_mapping = dict(zip(growth_df['id'], growth_df['color_name_hex']))
    name_mapping = dict(zip(growth_df['id'], growth_df['name']))

    # Create a date range from min to max date
    date_range = pd.date_range(start=growth_df['dt'].min(), end=growth_df['dt'].max())

    # Plot the growth for each stock
    fig, ax = plt.subplots(figsize=(15, 5))

    # Get a list of unique stock ids
    stock_ids = growth_df['id'].unique()

    # Plot each stock's growth over time
    for id in stock_ids:
        stock_growth = growth_df[growth_df['id'] == id]
        
        # We need to reindex the growth data to include all dates, filling missing values with 0 growth
        stock_growth.set_index('dt', inplace=True)
        stock_growth = stock_growth.reindex(date_range, fill_value=0).reset_index().rename(columns={'index': 'dt'})
        
        # Plotting the growth
        ax.plot(stock_growth['dt'], stock_growth['growth'], color='gray', linewidth=2)
        ax.plot(stock_growth['dt'], stock_growth['growth'], label=name_mapping[id], color=color_mapping[id], linewidth=1.5)

    # indicate changes
    for change_date in change_dates_df['dt']:
        ax.axvline(x=change_date, color='gray', linestyle=':')
    
    # Plot growth = 0 line:
    ax.axhline(y=0, color='black', linestyle='-', linewidth=1)

    # Formatting the plot
    ax.legend(loc='upper left', fontsize='small')
    ax.set_title('Stock Profit Growth Over Time')
    ax.set_xlabel('Date')
    ax.set_ylabel('Growth')
    plt.xticks(rotation=45)
    plt.tight_layout()

    # Show the plot
    #plt.show()

    # Saving the plot as an image:

    fig.savefig(os.path.join(visual_reports_dir, 'growth' + '.png'))
    plt.close(fig)  # Close the figure to free memory




# Generating colors:
def generate_and_store_colors(engine, num_colors=50):

    cmaps_list = ['tab20', 'tab20b', 'tab20c']

    # Generate the list of color hex codes
    colors = []
    for cmap_name in cmaps_list:
        cmap = plt.get_cmap(cmap_name)
        # Extract colors from the colormap
        for i in range(cmap.N):
            rgb = cmap(i)[:3]  # will return rgba, we take only first 3 to get rgb
            colors.append(rgb)
    # Deduplicate colors
    unique_colors = list(dict.fromkeys(colors))
    # If we have more unique colors than needed, truncate the list
    if len(unique_colors) > num_colors:
        unique_colors = unique_colors[:num_colors]
    # Convert RGB to Hex
    color_hex_codes = [to_hex(color) for color in unique_colors]

    # Create a DataFrame with color IDs and their hex codes
    colors_df = pd.DataFrame({'color_id': range(1, len(color_hex_codes) + 1), 'color_name_hex': color_hex_codes})

    # Insert the DataFrame into the 'colors' table
    colors_df.to_sql('colors', engine, if_exists='replace', index=False, method='multi')



############################################################################################ 
################################### IMPORTANT TRIGGERS: ####################################
############################################################################################

def important_triggers(engine):

    message_list = []

    ### Look for important events:
    with engine.connect() as conn:

        total_profit = """
                            SELECT
                                total_profit
                            FROM portfolio
                            WHERE total_profit > 500
                            ORDER BY DT DESC
                            LIMIT 1
                        """
        tax_free_profit = pd.read_sql(total_profit, conn)

    if not tax_free_profit.empty:
        message_list.append('TAX FREE PROFIT ALERT: you can only cash out 500 euros per year without paying taxes.')


    return message_list






####################################################################################### 
################################### TELEGRAM CHAT: ####################################
####################################################################################### 
    


async def telegram_send_updates(engine, token, chatId, visual_reports_dir, trigger_messages):

    bot = Bot(token=token)

    ### Construct summary:
    with engine.connect() as conn:
        profit_over_time = """
                        SELECT
                            *
                        FROM portfolio
                        ORDER BY dt DESC
                        LIMIT 1
                        """
        profit_over_time_df = pd.read_sql(profit_over_time, conn)
    profit_dict = profit_over_time_df.iloc[0].to_dict()

    message_lines = ['Portfolio Summary:']
    for key, value in profit_dict.items():
            label = key.replace("_", " ").capitalize()
            if value is None:
                message_lines.append(f'{label}: No change')
            elif isinstance(value, float):
                message_lines.append(f'{label}: {value:.3f}')
            else:
                message_lines.append(f'{label}: {value}')

    # Join the message lines into a single string
    message = '\n'.join(message_lines)

    await bot.send_message(chat_id=chatId, text=message)
    

    ### Construct and send the media group message:
    image_paths = [
        visual_reports_dir+'\\combined_profits.png',
        visual_reports_dir+'\\growth.png',
        visual_reports_dir+'\\total_portfolio.png'
    ]

    media_group = [InputMediaPhoto(open(path, 'rb').read(), caption=path.split('\\')[-1]) for path in image_paths]

    await bot.send_media_group(chat_id=chatId, media=media_group)

    # Close all opened image files
    for path in image_paths:
        open(path, 'rb').close()


    ### Construct important messages:
    if trigger_messages:
        message = '\n'.join(trigger_messages)
        await bot.send_message(chat_id=chatId, text=message)




