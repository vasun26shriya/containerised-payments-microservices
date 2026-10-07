// Runs only when the secured demo's separate MongoDB volume is initialized.
const fs = require('fs');
for (const service of ['orders', 'payments']) {
  const password = fs.readFileSync(`/run/secrets/${service}-db-password`, 'utf8').trim();
  db.getSiblingDB(service).createUser({
    user: service, pwd: password, roles: [{ role: 'readWrite', db: service }]
  });
}
