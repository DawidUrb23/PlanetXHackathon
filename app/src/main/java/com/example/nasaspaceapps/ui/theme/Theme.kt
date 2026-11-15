package com.example.nasaspaceapps.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable

private val CosmicColorScheme = darkColorScheme(
    primary = CosmicBlue,
    secondary = NebulaPurple,
    tertiary = GlowCyan,
    background = SpaceBlack,
    surface = SpaceDarkSurface,
    onPrimary = SpaceBlack,
    onSecondary = StarWhite,
    onTertiary = SpaceBlack,
    onBackground = StarWhite,
    onSurface = StarWhite
)

@Composable
fun NasaSpaceAppsTheme(
    darkTheme: Boolean = true,
    dynamicColor: Boolean = false,
    content: @Composable () -> Unit
) {
    MaterialTheme(
        colorScheme = CosmicColorScheme,
        typography = Typography,
        content = content
    )
}
