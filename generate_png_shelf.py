import os
import time
import subprocess
import matplotlib.pyplot as plt
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Configuration
log_directory = '/home/xxxx/Documents/labconco_log/data/6port/'
alert_flag_file = 'alert_active.flag'
alert_duration_hours = 0.25  # 15 minutes
pressure_threshold = 1000  # microBar
temperature_threshold = -35

alert_sent = {
    "vacuum": False,
    "temperature": False,
    "defrost": False
}

def send_alert(alert_type):
    print(f"Sending alert: {alert_type}")
    try:
        subprocess.run(['python3', 'send_alert_email.py', alert_type], check=True)
    except Exception as e:
        print(f"Failed to send alert: {e}")
        
def log_alert_event(alert_type):
    with open('alert_log.txt', 'a') as log_file:
        log_file.write(f"{datetime.now().isoformat()} - ALERT: {alert_type}\n")

def check_continuous_segment(hours, condition_mask, min_duration):
    if not hours or not condition_mask or len(hours) != len(condition_mask):
        return False

    total_span = hours[-1] - hours[0]

    # If the total time span is shorter than min_duration
    if total_span < min_duration:
        return all(condition_mask)

    # Otherwise, check the most recent continuous True segment
    active_segment = []

    for h, c in zip(hours, condition_mask):
        if c:
            active_segment.append(h)
        else:
            active_segment = []

    if len(active_segment) < 2:
        return False

    duration = active_segment[-1] - active_segment[0]
    return duration >= min_duration

def process_log_file(filepath):
    t_values = []
    v_values = []
    st_values = []
    p1_values = []
    p2_values = []
    p3_values = []
    sv_values = []
    hours = []

    with open(filepath, 'r') as file:
        for line in file:
            if 'V=' in line and 'T=' in line:
                try:
                    timestamp_str = line.split()[0]
                    time_obj = datetime.strptime(timestamp_str, '%H%M%S')
                    hour = time_obj.hour + time_obj.minute / 60 + time_obj.second / 3600

                    bline = line.split(" ", 1)[1]
                    t_value = float(bline.split('T=')[1].split('V=')[0].replace(' ', ''))
                    v_value = float(bline.split('V=')[1].split('SF=')[0].replace(' ', ''))

                    if 'TD<' in line and '>' in line:
                        sline = line.split('<')[2].split('>')[0]
                        st_value = float(sline.split('ST=')[1].split('P1=')[0].replace(' ', ''))
                        p1_value = float(sline.split('P1=')[1].split('P2=')[0].replace(' ', ''))
                        p2_value = float(sline.split('P2=')[1].split('P3=')[0].replace(' ', ''))
                        p3_value = float(sline.split('P3=')[1].split('V=')[0].replace(' ', ''))
                        sv_value = float(sline.split('V=')[1].split()[0].replace(' ', ''))
                    else:
                        st_value = p1_value = p2_value = p3_value = sv_value = None

                    hours.append(hour)
                    t_values.append(t_value)
                    v_values.append(v_value)

                    if st_value is not None: st_values.append((hour, st_value))
                    if p1_value is not None: p1_values.append((hour, p1_value))
                    if p2_value is not None: p2_values.append((hour, p2_value))
                    if p3_value is not None: p3_values.append((hour, p3_value))
                    if sv_value is not None: sv_values.append((hour, sv_value))
                except Exception:
                    continue
    if not hours:
        print("No valid data found.")
        return

    low_temp = [t < temperature_threshold for t in t_values]
    high_vacuum = [v > pressure_threshold for v in v_values]

    low_temp_duration = check_continuous_segment(hours, low_temp, alert_duration_hours)
    high_vacuum_duration = check_continuous_segment(hours, high_vacuum, alert_duration_hours)

    alert_active = os.path.exists(alert_flag_file)
    alert_type = None

    if low_temp_duration and not high_vacuum_duration:
        alert_type = None
    elif low_temp_duration and high_vacuum_duration:
        alert_type = "Vacuum"
    elif not low_temp_duration and not high_vacuum_duration:
        alert_type = "Temperature"
    elif not low_temp_duration and high_vacuum_duration:
        alert_type = "Defrosting"

    if alert_type and not alert_active:
        send_alert(alert_type)
        with open(alert_flag_file, 'w') as f:
            f.write(alert_type)
        log_alert_event(alert_type)
    elif not alert_type and alert_active:
        os.remove(alert_flag_file)
        log_alert_event("Alert cleared")
        print("Alert cleared.")

    # Plot
    fig, axs = plt.subplots(2, 1, sharex=True)
    axs[0].plot(hours, v_values, '.-', label='Base Pressure')
    axs[0].plot([x[0] for x in sv_values], [x[1] for x in sv_values], '.-', label='Shelf Pressure')
    axs[0].set_ylabel('Pressure / µBar')
    axs[0].set_yscale('log')
    axs[0].set_ylim(5, 5000)
    axs[0].set_title('6port_' + datetime.now().strftime('%y%m%d'))
    axs[0].legend(loc='center left', bbox_to_anchor=(1, 0.5))

    axs[1].plot([x[0] for x in st_values], [x[1] for x in st_values], '.-', label='Shelf Temp')
    axs[1].plot([x[0] for x in p1_values], [x[1] for x in p1_values], '.-', label='Probe 1 Temp')
    axs[1].plot([x[0] for x in p2_values], [x[1] for x in p2_values], '.-', label='Probe 2 Temp')
    axs[1].plot([x[0] for x in p3_values], [x[1] for x in p3_values], '.-', label='Probe 3 Temp')
    axs[1].plot(hours, t_values, '.-', label='Collector Temp')
    axs[1].set_ylabel('Temperature / °C')
    axs[1].set_xlabel('Hour')
    axs[1].set_xlim(0, 24)
    axs[1].set_ylim(-60, 30)
    axs[1].legend(loc='center left', bbox_to_anchor=(1, 0.5))

    fig.tight_layout()
    png_filename = filepath.replace('.txt', '.png')
    plt.savefig(png_filename, bbox_inches="tight")
    plt.close()
    print(f"Updated plot: {png_filename}")

# Monitor
filename = os.path.join(log_directory, datetime.now().strftime('%y%m%d') + '.txt')
newfilename = filename

while newfilename == filename:
    filename = os.path.join(log_directory, datetime.now().strftime('%y%m%d') + '.txt')
    if os.path.exists(filename):
        process_log_file(filename)
    else:
        print(f"{filename} not found. Waiting...")

    time.sleep(60)  # Wait for 1 minute before repeating
