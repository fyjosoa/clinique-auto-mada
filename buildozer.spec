[app]

title = Clinique Auto Mada
package.name = cliniqueautomada
package.domain = mg.cliniqueautomada

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,pdf,ttf,txt

version = 8.1.0

# sqlite3 : indispensable (la base de données plante sinon sur Android)
# pillow / typing_extensions : dépendances de reportlab et pypdf
requirements = python3,kivy,sqlite3,pillow,typing_extensions,reportlab,pypdf,androidstorage4kivy

# Portrait + paysage : l'écran s'adapte automatiquement à la rotation
orientation = portrait,landscape
fullscreen = 0

# API 33 : version stable avec python-for-android ; l'APK s'installe et tourne sur Android 14
android.api = 33
android.ndk = 25b
android.minapi = 24
android.archs = arm64-v8a,armeabi-v7a
android.accept_sdk_license = True

android.permissions = INTERNET


[buildozer]

log_level = 2
warn_on_root = 1
