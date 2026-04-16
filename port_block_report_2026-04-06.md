# Port-block report (2026-04-06)

## Summary
Applied UFW deny rules for IPs with heavy blocked traffic in the last 24h.

## Source logs
- /var/log/ufw.log
- /var/log/ufw.log.1 (not used for last-24h window)

## Policy used
- Window: last 24 hours
- Threshold: >= 20 blocked attempts per IP
- Block type: deny **by IP** (all ports)
- Whitelist: 127.0.0.0/8, ::1/128, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 192.168.1.0/24, 192.168.100.0/24

## IPs blocked
- 161.81.61.72 (256)
- 176.65.151.74 (192)
- 79.124.62.230 (99)
- 79.124.62.126 (74)
- 115.231.78.11 (52)
- 165.22.30.221 (36)
- 79.124.40.114 (35)
- 45.205.1.110 (30)
- 89.248.163.168 (28)
- 85.217.149.6 (21)
- 45.205.1.5 (20)

## Commands executed
- sudo /usr/sbin/ufw status verbose
- sudo head -n 5 /var/log/ufw.log
- sudo python3 (log parser, last 24h, >=20)
- sudo bash -lc 'for ip in ...; do /usr/sbin/ufw deny from "$ip" to any; done'

## Notes
If you want this to run daily, we can schedule a cron job to parse `/var/log/ufw.log` and apply new blocks automatically.
