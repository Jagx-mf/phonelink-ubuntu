plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.phonelink.companion"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.phonelink.companion"
        minSdk = 24          // Android 7.0 — couvre la grande majorité des appareils
        targetSdk = 34
        versionCode = 7
        versionName = "1.0.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        viewBinding = true
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")

    // Serveur HTTP embarqué léger (~50 Ko, une seule classe à étendre).
    // org.json est fourni par la plateforme Android (aucune dépendance JSON tierce).
    implementation("org.nanohttpd:nanohttpd:2.3.1")
}
