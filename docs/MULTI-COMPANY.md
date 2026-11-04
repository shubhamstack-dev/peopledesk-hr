# Multiple companies (SaaS)

Any company can register at the sign-in page (**Register your company**). Each registered company gets its own
MySQL database; nothing is shared between companies.

* `pd_tenants` (in the configured database, `peopledesk`) lists the registered companies: code, name, database.
* The first company to register uses the configured database itself. Every later company gets `peopledesk_<code>`.
* A database that already holds a company when this version first starts is registered automatically; its code is
  its short company code in lower case (for example `aipl`).
* People sign in with the company code, their e-mail and password (or Microsoft / Google). A link
  `https://<site>/?org=<code>` fills the code in. E-mails from the app include it.
* A session belongs to one company and only ever opens that company's database. Uploaded files are stored per
  company under `uploads/<company id>/`.

## One-time database permission

New companies need the database user to be allowed to create their databases. Run once as root:

```sql
GRANT ALL PRIVILEGES ON `peopledesk\_%`.* TO 'peopledesk'@'%';
FLUSH PRIVILEGES;
```

## Settings

* `MAX_TENANTS` (default 100): the most companies that can register.
* Registrations are limited to 5 an hour from one network address.

## Backups

Back up every company's database, for example:

```sh
docker exec pd-mysql sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --databases $(mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -e "SHOW DATABASES LIKE \"peopledesk%\"")' > peopledesk-all.sql
```
