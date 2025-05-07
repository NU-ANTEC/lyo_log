# lyo_log
Logger for old Labconco Freezone lyophilizer. At Northwestern University's ANTEC core facility, we operate two mid-2010s Freezone 6 Plus lyophilizers, one with a stoppering shelf. We generated this code to monitor the instrument health and to provide users with sample logs. Tested on Raspberry Pi 3B+ running Bookworm. This set of script was prompt-engineered by ChatGPT and Copilot.

## Requirement

- A computer that can run Python
- Labconco cable for RS-232 (see below for alternative)
- RS232-USB converter cable
- Rclone (https://rclone.org) for uploading data
- Python 3 with pyserial, dotenv and matplotlib. I created a virtual environment and ran python inside.

## File description
- labconco_log.py: Records the RS-232 output line by line and outputs file per day. Purges older files at startup.
- generate_png.py: Outputs PNG plots every minute.
- generate_png_shelf.py: Outputs PNG plots for shelf lyophilizers. You can set the email alert threshold.
- send_email_alert.py: Subroutine for sending alert emails. Requires Gmail setup with .env.

Please read manuals from Labconco to understand the output format from the RS-232 port.
Example systemd services and timers are included.

## Alternative to Labconco cable (P/N 7537800)
- RJ12 cables (https://www.amazon.com/dp/B0C1VJV1JW/)
- DB9 to RJ12 converter (https://www.amazon.com/dp/B0779NCTG7/)

Below is the Labconco cable drawing.
![image](https://github.com/user-attachments/assets/d1e74c2f-63f0-4bc2-b2db-69833f65bb5d)

For the DB9-RJ12 converter, you need to connect *the rightmost wire (when looking into the port with notch up) from RJ12* to pin 2 on DB9, and the leftmost wire from RJ12 to pin 5 on DB9. If you flip this, the script will give you garbled readout.
