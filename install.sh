#!/bin/bash
set -eu

ES_ESS_DIR=/data/es-ESS
SERVICE_DIR=/service
SERVICE_LINK="$SERVICE_DIR/es-ESS"
SERVICE_TARGET="$ES_ESS_DIR/service"
RC_LOCAL=/data/rc.local
CONFIG_TARGET="$ES_ESS_DIR/config.ini"
CONFIG_SAMPLE="$ES_ESS_DIR/config.sample.ini"

# set permissions for script files
chmod 744 "$ES_ESS_DIR/restart.sh"
chmod 744 "$ES_ESS_DIR/kill_me.sh"
chmod 744 "$ES_ESS_DIR/uninstall.sh"
chmod 755 "$SERVICE_TARGET/run"

# create or repair sym-link to run script in deamon
mkdir -p "$SERVICE_DIR"
if [ -L "$SERVICE_LINK" ]; then
    if [ "$(readlink "$SERVICE_LINK")" != "$SERVICE_TARGET" ]; then
        rm -f "$SERVICE_LINK"
        ln -s "$SERVICE_TARGET" "$SERVICE_LINK"
    fi
elif [ -e "$SERVICE_LINK" ]; then
    echo "$SERVICE_LINK exists but is not a symlink; refusing to replace it" >&2
    exit 1
else
    ln -s "$SERVICE_TARGET" "$SERVICE_LINK"
fi

# add install-script to rc.local to be ready for firmware update
if [ ! -f "$RC_LOCAL" ]
then
    printf '#!/bin/bash\n\n' > "$RC_LOCAL"
    chmod 755 "$RC_LOCAL"
fi

grep -qxF '/data/es-ESS/install.sh' "$RC_LOCAL" || echo '/data/es-ESS/install.sh' >> "$RC_LOCAL"

#first install? need config.sample to be copied.
if [ ! -f "$CONFIG_TARGET" ]
then
    cp "$CONFIG_SAMPLE" "$CONFIG_TARGET"
fi
chmod 600 "$CONFIG_TARGET"
