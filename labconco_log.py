import os
import serial
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

# Directory where the log files are stored
log_directory = './data/24port/'

# Calculate the cutoff date (2 months ago)
cutoff_date = datetime.now() - timedelta(days=60)

# Serial port name, check with dmesg | grep tty
serial_port='/dev/ttyUSB0'

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

# Configure the serial connection
ser = serial.Serial(
    port=serial_port,       # Replace with your port name
    baudrate=2400,
    bytesize=serial.EIGHTBITS,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    timeout=1          # Timeout in seconds
)

# Generate the filename based on the current date

filename = log_directory + '/' + datetime.now().strftime('%y%m%d') + '.txt'
newfilename  = filename
# Open a file to record the output
with open(filename, 'a') as file:
    while newfilename == filename: # check date against filename
        try:
            # Read data from the serial port
            data = ser.readline().decode('utf-8').strip()
            if data:
                # Prepend the time in HHMMSS format
                timestamp = datetime.now().strftime('%H%M%S')
                log_entry = f"{timestamp} {data}"
                #print(log_entry)  # Print to console (optional)
                file.write(log_entry + '\n')  # Write to file
                file.flush()
                os.fsync(file.fileno())
                newfilename = log_directory + '/' + datetime.now().strftime('%y%m%d') + '.txt'
        except KeyboardInterrupt:
            print("Recording stopped by user.")
            file.close()
            break

# Close the serial connection
ser.close()

