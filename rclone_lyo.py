import os
import subprocess
from datetime import datetime, timedelta

# Directory where the log files are stored
log_directory = './data/24port/'

# Calculate the cutoff date (2 months ago)
cutoff_date = datetime.now() - timedelta(days=60)

# Delete log files older than 2 months
for filename in os.listdir(log_directory):
    if filename.endswith('.txt'):
        # Extract the date from the filename
        file_date_str = filename[:6]  # Assuming the format is YYMMDD.txt
        try:
            file_date = datetime.strptime(file_date_str, '%y%m%d')
            # Check if the file is older than the cutoff date
            if file_date < cutoff_date:
                file_path = os.path.join(log_directory, filename)
                os.remove(file_path)
                print(f"Deleted {file_path}")
        except ValueError:
            # Skip files that don't match the date format
            continue

# Define the command
command = "/usr/bin/rclone copy /home/xxxx/Documents/labconco_log/data/ xxxx:lyo_log/data/"

# Run the command
process = subprocess.run(command, shell=True, check=True)

# Check the result
if process.returncode == 0:
    print("Command executed successfully!")
else:
    print("There was an error executing the command.")
