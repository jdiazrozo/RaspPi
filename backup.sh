#!/bin/sh

cd /home/pi/
tar czf personalapp.tar.gz personalapp
mv personalapp.tar.gz /media/USBHDD1/shares/Backups/Backup_Pi/personalapp.tar.gz

cd /usr/lib/
tar czf cgi-bin.tar.gz cgi-bin
mv cgi-bin.tar.gz /media/USBHDD1/shares/Backups/Backup_Pi/cgi-bin.tar.gz

cd /var/
tar czf www.tar.gz www
mv www.tar.gz /media/USBHDD1/shares/Backups/Backup_Pi/www.tar.gz

cd /var/spool/cron
tar czf crontabs.tar.gz crontabs
mv crontabs.tar.gz /media/USBHDD1/shares/Backups/Backup_Pi/cron.tar.gz

