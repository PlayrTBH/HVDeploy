#!/usr/bin/env bash
set -euo pipefail

log() {
    printf '\n[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

abort() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

require_command() {
    local cmd="$1"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        return 1
    fi
    return 0
}

ensure_root_capability() {
    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
        SUDO=""
    elif require_command sudo; then
        SUDO="sudo"
    else
        abort "This installer must be run as root or with sudo."
    fi
}

ensure_supported_os() {
    if require_command apt-get; then
        PACKAGE_MANAGER="apt"
    else
        abort "Unsupported distribution. Only Debian/Ubuntu systems with apt-get are currently supported."
    fi
}

install_packages() {
    if [[ "$PACKAGE_MANAGER" == "apt" ]]; then
        local packages=(apache2 git php libapache2-mod-php php-cli)
        log "Updating apt cache and installing required packages (${packages[*]})."
        $SUDO apt-get update -y
        $SUDO apt-get install -y "${packages[@]}"
    fi
}

clone_or_update_repo() {
    local repo_url="$1"
    local branch="$2"
    local install_dir="$3"

    if [[ -d "$install_dir/.git" ]]; then
        log "Repository already exists at $install_dir. Pulling latest changes from $branch."
        (cd "$install_dir" && $SUDO git fetch --depth=1 origin "$branch")
        (cd "$install_dir" && $SUDO git reset --hard "origin/$branch")
    else
        log "Cloning $repo_url (branch: $branch) into $install_dir."
        $SUDO rm -rf "$install_dir"
        $SUDO git clone --depth=1 --branch "$branch" "$repo_url" "$install_dir"
    fi
}

configure_permissions() {
    local install_dir="$1"
    local apache_user="$2"
    local apache_group="$3"

    log "Configuring permissions for data directory."
    $SUDO mkdir -p "$install_dir/data"
    $SUDO touch "$install_dir/data/links.json"
    $SUDO chown -R "$apache_user:$apache_group" "$install_dir/data"
    $SUDO chmod 770 "$install_dir/data"
    $SUDO chmod 660 "$install_dir/data/links.json"
}

configure_apache() {
    local install_dir="$1"
    local site_name="$2"
    local server_name="$3"

    log "Writing Apache virtual host configuration ($site_name)."
    local site_path="/etc/apache2/sites-available/${site_name}.conf"
    cat <<SITE | $SUDO tee "$site_path" >/dev/null
<VirtualHost *:80>
    ServerName $server_name
    DocumentRoot $install_dir/public

    <Directory $install_dir/public>
        Options Indexes FollowSymLinks
        AllowOverride All
        Require all granted
    </Directory>

    ErrorLog \${APACHE_LOG_DIR}/${site_name}-error.log
    CustomLog \${APACHE_LOG_DIR}/${site_name}-access.log combined
</VirtualHost>
SITE

    log "Enabling required Apache modules and site."
    $SUDO a2enmod rewrite
    $SUDO a2ensite "$site_name"

    if [[ -e /etc/apache2/sites-enabled/000-default.conf ]]; then
        $SUDO a2dissite 000-default >/dev/null 2>&1 || true
    fi

    log "Reloading Apache service."
    $SUDO systemctl reload apache2
}

main() {
    ensure_root_capability
    ensure_supported_os

    local repo_url="${HVDEPLOY_REPO:-https://github.com/HVDeploy/HVDeploy.git}"
    local branch="${HVDEPLOY_BRANCH:-main}"
    local install_dir="${HVDEPLOY_DIR:-/opt/service-hub}"
    local apache_user="${HVDEPLOY_APACHE_USER:-www-data}"
    local apache_group="${HVDEPLOY_APACHE_GROUP:-$apache_user}"
    local site_name="${HVDEPLOY_SITE_NAME:-service-hub}"
    local server_name="${HVDEPLOY_SERVER_NAME:-service-hub.local}"
    local configure_apache_flag="${HVDEPLOY_CONFIGURE_APACHE:-1}"

    if [[ "$repo_url" == *"HVDeploy/HVDeploy.git" && "${HVDEPLOY_REPO:-}" == "" ]]; then
        log "Using default repository URL ($repo_url). Override with HVDEPLOY_REPO to use a fork."
    fi

    install_packages
    clone_or_update_repo "$repo_url" "$branch" "$install_dir"
    configure_permissions "$install_dir" "$apache_user" "$apache_group"

    if [[ "$configure_apache_flag" == "1" ]]; then
        configure_apache "$install_dir" "$site_name" "$server_name"
    else
        log "Skipping Apache virtual host configuration (HVDEPLOY_CONFIGURE_APACHE=$configure_apache_flag)."
    fi

    log "Installation complete!"
    printf '\nNext steps:\n'
    printf '  1. Update the default admin password in %s/config.php.\n' "$install_dir"
    printf '  2. Restart Apache if you made additional configuration changes.\n'
    printf '  3. Visit http://%s and log in with the default credentials (admin / change_me).\n\n' "$server_name"
}

main "$@"
