// OnlyBrowserOS: load /usr/lib/firefox-esr/onlybrowseros.cfg at startup.
// It sets the new-tab page, which no preference or policy can do.
pref("general.config.filename", "onlybrowseros.cfg");
pref("general.config.obscure_value", 0);
pref("general.config.sandbox_enabled", false);
