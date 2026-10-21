# deploy-platform (example project)

> Status doc for octopus-auto. One top-level bullet = one ticket; the bold text is the title.

## ✅ Done
- **Per-account bootstrap stack** — state bucket, KMS key and an OIDC deploy role per account
- **CD receiver workflow** — service repos dispatch a deploy; one deploy per service and environment at a time
- **Service spec renderer** — a short service file renders to a full, schema-validated task definition
- **Circuit breaker with auto-rollback** — a failed rollout returns to the last good version without anyone stepping in

## 🔄 Ongoing
- **Production approval gate** — working on it; required reviewer on the production environment
- **Image cleanup policy** — Next: keep the last 20 images per repository
- **Cross-account DNS writer** — waiting for the DNS account owner to create the role

## 📋 Upcoming
- **Spot capacity for non-prod** — about 70% cheaper compute for dev and sandbox
- **Memory-based autoscaling** — CPU is the only scaling signal today
- **Teardown mode for the deploy script** — offboarding a service is still manual
