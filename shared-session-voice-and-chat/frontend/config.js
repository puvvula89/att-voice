// Frontend runtime config. The deploy script (deploy/deploy_all.sh) overwrites
// this with the deployed relay's wss:// URL before deploying the UI. The
// committed default points at a local relay for dev.
window.RELAY_URL = "ws://localhost:8000";
