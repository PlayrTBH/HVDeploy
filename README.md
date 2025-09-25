# Service Hub Web Portal

Service Hub is a lightweight PHP application designed to run behind Apache HTTP Server and provide a secure dashboard for all of your self-hosted tools. After signing in, you can curate a list of links to your internal services and launch them directly from the portal.

## Features

- Password-protected login backed by PHP sessions.
- Simple interface for adding and removing service links.
- Links are stored locally in `data/links.json` so they persist across restarts.
- Minimal styling that looks great on desktops and mobile devices.

## Requirements

- Apache HTTP Server with PHP 8.1 or later enabled (the bundled code uses standard PHP features—no database required).
- Write access for the Apache user to the `data/` directory so that new links can be saved.

## Project structure

```text
config.php            Application configuration (default credentials and data file path)
data/links.json       JSON store for saved links
public/               Web root that should be exposed by Apache
  index.php           Login page
  dashboard.php       Authenticated control panel and link manager
  logout.php          Session termination endpoint
  assets/styles.css   Shared styling for login and dashboard views
```

## Installation

### Quick install script (Debian/Ubuntu)

```bash
curl -fsSL https://raw.githubusercontent.com/HVDeploy/HVDeploy/main/install.sh | sudo bash
```

Set the `HVDEPLOY_REPO`, `HVDEPLOY_BRANCH`, or `HVDEPLOY_DIR` environment variables to customize the source repository, branch, or installation path. For example, to install from a fork located at `https://github.com/your-org/HVDeploy.git` run:

```bash
curl -fsSL https://raw.githubusercontent.com/HVDeploy/HVDeploy/main/install.sh | sudo HVDEPLOY_REPO=https://github.com/your-org/HVDeploy.git bash
```

The script installs Apache, PHP, and git (via `apt-get`), checks out the application to `/opt/service-hub`, configures permissions on `data/`, and optionally provisions an Apache virtual host pointing to the `public/` directory. Override `HVDEPLOY_CONFIGURE_APACHE=0` to skip the virtual host creation.

1. **Clone or copy the project to your server.**
2. **Point Apache's `DocumentRoot` at the `public/` directory.** Example virtual host:

   ```apacheconf
   <VirtualHost *:80>
       ServerName portal.local
       DocumentRoot /var/www/service-hub/public

       <Directory /var/www/service-hub/public>
           AllowOverride All
           Require all granted
       </Directory>

       ErrorLog ${APACHE_LOG_DIR}/service-hub-error.log
       CustomLog ${APACHE_LOG_DIR}/service-hub-access.log combined
   </VirtualHost>
   ```

3. **Ensure the Apache user can write to `data/links.json`.**

   ```bash
   sudo chown www-data:www-data /var/www/service-hub/data/links.json
   sudo chmod 660 /var/www/service-hub/data/links.json
   ```

4. **Update the admin password (recommended).** Edit `config.php` and replace the hash with your own. Generate a secure hash with PHP:

   ```bash
   php -r "echo password_hash('your-new-password', PASSWORD_DEFAULT), PHP_EOL;"
   ```

   Copy the resulting hash into the `config.php` `users` array.

5. **Restart Apache** (if necessary) and visit the site. The default credentials are `admin` / `change_me`.

## Usage

- **Log in** using your configured credentials.
- **Add a link** by providing a label and a valid URL. Links are immediately saved to `data/links.json`.
- **Remove a link** by clicking the *Remove* button next to any existing entry.
- **Log out** using the button in the header when you are done.

## Security considerations

- Change the default password before exposing the portal to any network.
- Restrict network access to trusted subnets using Apache configuration or a reverse proxy.
- Consider serving the portal exclusively over HTTPS to protect credentials in transit.
