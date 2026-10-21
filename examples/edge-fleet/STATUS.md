# edge-fleet (example project)

> Status doc for octopus-auto. One top-level bullet = one ticket; the bold text is the title.

## ✅ Done
- **Server creation as code** — OpenTofu module for one web server: instance, security group, elastic IP, DNS record
- **Config management roles** — Ansible roles for base, nginx, node, process manager, TLS and monitoring exporters
- **First service fully on code** — provisioned, configured and cut over with a DNS switch; old box kept for rollback
- **Request-time DNS resolution for upstreams** — static upstream hostnames made nginx fail to start on a DNS blip; resolved per request now

## 🔄 Ongoing
- **Migrate the remaining services** — working on it; 6 of 20 done, one service at a time
- **Fleet-wide SSH lockdown** — blocked on the office VPN CIDR from the network team
- **Monitoring auto-registration** — Next: decide between service discovery on tags and a generated target file

## 📋 Upcoming
- **CI for the platform itself** — plan on PR, gated apply, no laptop runs against production
- **Retry flaky package mirrors** — onboarding sometimes aborts on mirror timeouts
- **Release unused elastic IPs** — only after DNS no longer points at them
