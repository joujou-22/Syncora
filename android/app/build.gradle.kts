plugins {
    id("com.android.application")
}

android {
    namespace = "org.syncora.client"
    compileSdk {
        version = release(36) {
            minorApiLevel = 1
        }
    }

    defaultConfig {
        applicationId = "org.syncora.client"
        minSdk = 23
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
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
}

dependencies {
    // M144 aborts in network_thread on some Android 9 armeabi-v7a TV firmware.
    // M125 keeps modern Unified Plan/H.264 support with broader legacy runtime compatibility.
    implementation("io.github.webrtc-sdk:android:125.6422.07")
    implementation("androidx.media3:media3-exoplayer:1.10.1")
    implementation("androidx.media3:media3-exoplayer-rtsp:1.10.1")
}
