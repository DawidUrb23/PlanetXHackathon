package com.example.nasaspaceapps
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.TextButton
import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.location.Location
import android.net.Uri
import android.os.Bundle
import android.util.Log
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Send
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.example.nasaspaceapps.ui.theme.CosmicBlue
import com.example.nasaspaceapps.ui.theme.NasaSpaceAppsTheme
import com.example.nasaspaceapps.ui.theme.NebulaPurple
import com.example.nasaspaceapps.ui.theme.SpaceBlack
import com.example.nasaspaceapps.ui.theme.SpaceDarkSurface
import com.example.nasaspaceapps.ui.theme.StarWhite
import com.google.android.gms.location.LocationServices
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.acos
import kotlin.math.asin
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

private const val API_URL = "https://journey-convertible-evidence-flame.trycloudflare.com"

class MainActivity : ComponentActivity() {
    private val requestPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        val cameraGranted = permissions[Manifest.permission.CAMERA] ?: false
        if (!cameraGranted) {
            Toast.makeText(this, "Wymagane uprawnienie do aparatu", Toast.LENGTH_LONG).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        requestPermissionLauncher.launch(
            arrayOf(
                Manifest.permission.CAMERA,
                Manifest.permission.ACCESS_FINE_LOCATION,
                Manifest.permission.ACCESS_COARSE_LOCATION
            )
        )

        val outputDir = getOutputDirectory()

        setContent {
            NasaSpaceAppsTheme {
                var inGalaxyPortal by remember { mutableStateOf(true) }
                var currentScreen by remember { mutableStateOf<Screen>(Screen.Camera) }
                var photos by remember { mutableStateOf(loadPhotos(outputDir)) }

                fun refreshPhotos() {
                    photos = loadPhotos(outputDir)
                }

                if (inGalaxyPortal) {
                    GalaxyPortalScreen(
                        onEnterSpace = { inGalaxyPortal = false }
                    )
                } else {
                    when (val screen = currentScreen) {
                        is Screen.Camera -> {
                            CameraView(
                                outputDirectory = outputDir,
                                onPhotoCaptured = { refreshPhotos() },
                                onStarsReceived = { allSkyStars ->
                                    refreshPhotos()
                                    currentScreen = Screen.StarMap(allSkyStars)
                                },
                                onOpenGallery = {
                                    refreshPhotos()
                                    currentScreen = Screen.Gallery
                                },
                                photoCount = photos.size
                            )
                        }
                        is Screen.Gallery -> {
                            GalleryScreen(
                                photos = photos,
                                onPhotoClick = { photoItem ->
                                    currentScreen = Screen.Detail(photoItem)
                                },
                                onBack = {
                                    currentScreen = Screen.Camera
                                }
                            )
                        }
                        is Screen.Detail -> {
                            PhotoDetailScreen(
                                photoItem = screen.photoItem,
                                onBack = {
                                    refreshPhotos()
                                    currentScreen = Screen.Gallery
                                },
                                onStarsReceived = { allSkyStars ->
                                    refreshPhotos()
                                    currentScreen = Screen.StarMap(allSkyStars)
                                },
                                onDelete = { photoItem ->
                                    photoItem.imageFile.delete()
                                    photoItem.jsonFile.delete()
                                    refreshPhotos()
                                }
                            )
                        }
                        is Screen.StarMap -> {
                            StarMapScreen(
                                stars = screen.stars,
                                onBack = {
                                    currentScreen = Screen.Camera
                                }
                            )
                        }
                    }
                }
            }
        }
    }

    private fun getOutputDirectory(): File {
        val mediaDir = externalMediaDirs.firstOrNull()?.let {
            File(it, "SpaceAppsPhotos").apply { mkdirs() }
        }
        return if (mediaDir != null && mediaDir.exists()) mediaDir else filesDir
    }
}

// --------------------------------------------------------------------------
// Modele danych
// --------------------------------------------------------------------------
data class Star(
    val id: String,
    val name: String,
    val type: String,
    val magnitude: Float,
    val raDeg: Double = 0.0,
    val decDeg: Double = 0.0,
    val sepDeg: Double? = null,
    var description: String = "",
    var imageUrls: List<String> = emptyList()
)

data class PhotoItem(
    val imageFile: File,
    val jsonFile: File,
    val timestamp: String,
    val latitude: Double?,
    val longitude: Double?,
    val gyroX: Float?,
    val gyroY: Float?,
    val gyroZ: Float?,
    val accelX: Float?,
    val accelY: Float?,
    val accelZ: Float?,
    val azimuth: Float?,
    val pitch: Float?,
    val roll: Float?,
    val targetRa: Double? = null,
    val targetDec: Double? = null,
    val detectedObjects: List<Star> = emptyList()
)

sealed interface Screen {
    object Camera : Screen
    object Gallery : Screen
    data class Detail(val photoItem: PhotoItem) : Screen
    data class StarMap(val stars: List<Star>) : Screen
}

// --------------------------------------------------------------------------
// Silnik astronomiczny i stabilne rzutowanie 3D na ekran AR
// --------------------------------------------------------------------------
object AstroMath {
    fun getLocalSiderealTimeDeg(lonDeg: Double, timeMillis: Long = System.currentTimeMillis()): Double {
        val jd = (timeMillis / 86400000.0) + 2440587.5
        val d = jd - 2451545.0
        val gmst = (280.46061837 + 360.98564736629 * d) % 360.0
        val lst = (gmst + lonDeg) % 360.0
        return if (lst < 0) lst + 360.0 else lst
    }

    fun getZenithEquatorial(latDeg: Double, lonDeg: Double, timeMillis: Long = System.currentTimeMillis()): Pair<Double, Double> {
        return Pair(getLocalSiderealTimeDeg(lonDeg, timeMillis), latDeg)
    }

    fun horizontalToEquatorial(
        latDeg: Double,
        lonDeg: Double,
        azimuthDeg: Float,
        altitudeDeg: Float,
        timeMillis: Long = System.currentTimeMillis()
    ): Pair<Double, Double> {
        val altClamped = altitudeDeg.coerceIn(-89.9f, 89.9f).toDouble()
        val latRad = Math.toRadians(latDeg)
        val altRad = Math.toRadians(altClamped)
        val azRad = Math.toRadians(azimuthDeg.toDouble())

        val sinDec = sin(altRad) * sin(latRad) + cos(altRad) * cos(latRad) * cos(azRad)
        val decRad = asin(sinDec.coerceIn(-1.0, 1.0))

        val y = -sin(azRad) * cos(altRad)
        val x = (sin(altRad) - sin(decRad) * sin(latRad)) / (cos(decRad) * cos(latRad) + 1e-9)
        val haDeg = Math.toDegrees(atan2(y, x))

        val lstDeg = getLocalSiderealTimeDeg(lonDeg, timeMillis)
        var raDeg = (lstDeg - haDeg) % 360.0
        if (raDeg < 0) raDeg += 360.0

        return Pair(raDeg, Math.toDegrees(decRad))
    }

    fun angularSeparationDeg(ra1: Double, dec1: Double, ra2: Double, dec2: Double): Double {
        val r1 = Math.toRadians(ra1)
        val d1 = Math.toRadians(dec1)
        val r2 = Math.toRadians(ra2)
        val d2 = Math.toRadians(dec2)
        val cosSep = (sin(d1) * sin(d2) + cos(d1) * cos(d2) * cos(r1 - r2)).coerceIn(-1.0, 1.0)
        return Math.toDegrees(acos(cosSep))
    }

    /**
     * Zwraca jednostkowy wektor kierunku obiektu w układzie ENU (East, North, Up)
     * w nieskończoności (sfera niebieska).
     */
    fun equatorialToEnuVector(
        raDeg: Double,
        decDeg: Double,
        latDeg: Double,
        lonDeg: Double,
        timeMillis: Long = System.currentTimeMillis()
    ): FloatArray {
        val lstDeg = getLocalSiderealTimeDeg(lonDeg, timeMillis)
        val haRad = Math.toRadians(lstDeg - raDeg)
        val decRad = Math.toRadians(decDeg)
        val latRad = Math.toRadians(latDeg)

        val sinAlt = sin(decRad) * sin(latRad) + cos(decRad) * cos(latRad) * cos(haRad)
        val altRad = asin(sinAlt.coerceIn(-1.0, 1.0))

        val y = -sin(haRad) * cos(decRad)
        val x = (sin(decRad) - sin(altRad) * sin(latRad)) / (cos(altRad) * cos(latRad) + 1e-9)
        val azRad = atan2(y, x)

        // Wektor jednostkowy w układzie świata Androida: X = East, Y = North, Z = Up
        val east = (cos(altRad) * sin(azRad)).toFloat()
        val north = (cos(altRad) * cos(azRad)).toFloat()
        val up = sin(altRad).toFloat()

        return floatArrayOf(east, north, up)
    }

    /**
     * Rzutuje wektor świata ENU bezpośrednio przez macierz rotacji telefonu (3x3)
     * na współrzędne ekranu [0..1]. Brak kątów Eulera = brak skoków przy patrzeniu w górę
     * oraz ruch idealnie 1:1 z obrazem kamery (obiekt w nieskończoności).
     */
    fun projectEnuVectorToScreen(
        enuVec: FloatArray,
        rotationMatrix: FloatArray,
        fovHorizontalDeg: Float = 66f,
        fovVerticalDeg: Float = 84f
    ): Pair<Float, Float>? {
        // Mnożenie transponowanej macierzy rotacji R^T * v_world -> v_device
        // Układ urządzenia w trybie portretowym:
        // +X = prawa krawędź ekranu
        // +Y = górna krawędź ekranu
        // -Z = kierunek patrzenia tylnej kamery
        val devX = rotationMatrix[0] * enuVec[0] + rotationMatrix[3] * enuVec[1] + rotationMatrix[6] * enuVec[2]
        val devY = rotationMatrix[1] * enuVec[0] + rotationMatrix[4] * enuVec[1] + rotationMatrix[7] * enuVec[2]
        val devZ = rotationMatrix[2] * enuVec[0] + rotationMatrix[5] * enuVec[1] + rotationMatrix[8] * enuVec[2]

        // Tylna kamera patrzy wzdłuż -Z urządzenia. Jeśli devZ >= -0.15, obiekt jest za kamerą.
        val forward = -devZ
        if (forward <= 0.15f) return null

        val tanHalfFovX = kotlin.math.tan(Math.toRadians(fovHorizontalDeg / 2.0)).toFloat()
        val tanHalfFovY = kotlin.math.tan(Math.toRadians(fovVerticalDeg / 2.0)).toFloat()

        val normX = 0.5f + 0.5f * ((devX / forward) / tanHalfFovX)
        val normY = 0.5f - 0.5f * ((devY / forward) / tanHalfFovY)

        if (normX < -0.2f || normX > 1.2f || normY < -0.2f || normY > 1.2f) {
            return null
        }
        return Pair(normX, normY)
    }
}

    /**
     * Filtr dolnoprzepustowy dla kątów [0..360) eliminujący drgania rąk przy zachowaniu płynności.
     */
    fun smoothAngleDeg(current: Float, target: Float, alpha: Float = 0.22f): Float {
        var diff = target - current
        while (diff > 180f) diff -= 360f
        while (diff < -180f) diff += 360f
        return (current + alpha * diff + 360f) % 360f
    }

    fun smoothLinear(current: Float, target: Float, alpha: Float = 0.22f): Float {
        return current + alpha * (target - current)
    }


// --------------------------------------------------------------------------
// Odczyt orientacji tylnej kamery telefonu z sensora ROTATION_VECTOR
// --------------------------------------------------------------------------
fun computeCameraOrientationFromRotationVector(values: FloatArray): Triple<Float, Float, Float> {
    val rotationMatrix = FloatArray(9)
    val remappedMatrix = FloatArray(9)
    SensorManager.getRotationMatrixFromVector(rotationMatrix, values)

    // Oś Z urządzenia (tył telefonu z kamerą) staje się osią patrzenia
    SensorManager.remapCoordinateSystem(
        rotationMatrix,
        SensorManager.AXIS_X,
        SensorManager.AXIS_Z,
        remappedMatrix
    )

    val orientation = FloatArray(3)
    SensorManager.getOrientation(remappedMatrix, orientation)

    val azimuthDeg = (Math.toDegrees(orientation[0].toDouble()).toFloat() + 360f) % 360f
    // W remappedMatrix pitch = -altitude, więc altitude = -orientation[1]
    val altitudeDeg = -Math.toDegrees(orientation[1].toDouble()).toFloat()
    val rollDeg = Math.toDegrees(orientation[2].toDouble()).toFloat()

    return Triple(azimuthDeg, altitudeDeg, rollDeg)
}

// --------------------------------------------------------------------------
// Obsługa plików JSON (zapis i odczyt zdjęć + wykrytych obiektów)
// --------------------------------------------------------------------------
fun savePhotoMetadata(photoItem: PhotoItem) {
    try {
        val root = JSONObject().apply {
            put("timestamp", photoItem.timestamp)
            put("latitude", photoItem.latitude ?: 50.3)
            put("longitude", photoItem.longitude ?: 18.8)
            put("gyroX", photoItem.gyroX ?: 0f)
            put("gyroY", photoItem.gyroY ?: 0f)
            put("gyroZ", photoItem.gyroZ ?: 0f)
            put("accelX", photoItem.accelX ?: 0f)
            put("accelY", photoItem.accelY ?: 0f)
            put("accelZ", photoItem.accelZ ?: 0f)
            put("azimuth", photoItem.azimuth ?: 0f)
            put("pitch", photoItem.pitch ?: 0f)
            put("roll", photoItem.roll ?: 0f)
            if (photoItem.targetRa != null) put("targetRa", photoItem.targetRa)
            if (photoItem.targetDec != null) put("targetDec", photoItem.targetDec)

            val objectsArray = JSONArray()
            for (star in photoItem.detectedObjects) {
                val objJson = JSONObject().apply {
                    put("id", star.id)
                    put("name", star.name)
                    put("type", star.type)
                    put("magnitude", star.magnitude.toDouble())
                    put("ra", star.raDeg)
                    put("dec", star.decDeg)
                    put("description", star.description)
                    val imgs = JSONArray()
                    star.imageUrls.forEach { imgs.put(it) }
                    put("imageUrls", imgs)
                }
                objectsArray.put(objJson)
            }
            put("detected_objects", objectsArray)
        }
        photoItem.jsonFile.writeText(root.toString(2))
    } catch (e: Exception) {
        Log.e("SaveMetadata", "Błąd zapisu JSON", e)
    }
}

fun loadPhotos(outputDir: File): List<PhotoItem> {
    val jpgFiles = outputDir.listFiles { file -> file.extension.equals("jpg", true) }
        ?.sortedByDescending { it.lastModified() } ?: emptyList()

    return jpgFiles.map { jpg ->
        val json = File(jpg.absolutePath.replace(".jpg", ".json", true))
        var timestamp = "Brak daty"
        var lat: Double? = null
        var lon: Double? = null
        var gx: Float? = null
        var gy: Float? = null
        var gz: Float? = null
        var ax: Float? = null
        var ay: Float? = null
        var az: Float? = null
        var azim: Float? = null
        var pit: Float? = null
        var rol: Float? = null
        var targetRa: Double? = null
        var targetDec: Double? = null
        val detectedList = mutableListOf<Star>()

        if (json.exists()) {
            try {
                val root = JSONObject(json.readText())
                timestamp = root.optString("timestamp", timestamp)
                if (root.has("latitude")) lat = root.optDouble("latitude")
                if (root.has("longitude")) lon = root.optDouble("longitude")
                if (root.has("gyroX")) gx = root.optDouble("gyroX").toFloat()
                if (root.has("gyroY")) gy = root.optDouble("gyroY").toFloat()
                if (root.has("gyroZ")) gz = root.optDouble("gyroZ").toFloat()
                if (root.has("accelX")) ax = root.optDouble("accelX").toFloat()
                if (root.has("accelY")) ay = root.optDouble("accelY").toFloat()
                if (root.has("accelZ")) az = root.optDouble("accelZ").toFloat()
                if (root.has("azimuth")) azim = root.optDouble("azimuth").toFloat()
                if (root.has("pitch")) pit = root.optDouble("pitch").toFloat()
                if (root.has("roll")) rol = root.optDouble("roll").toFloat()
                if (root.has("targetRa")) targetRa = root.optDouble("targetRa")
                if (root.has("targetDec")) targetDec = root.optDouble("targetDec")

                val arr = root.optJSONArray("detected_objects")
                if (arr != null) {
                    for (i in 0 until arr.length()) {
                        val o = arr.getJSONObject(i)
                        val imgsArr = o.optJSONArray("imageUrls")
                        val imgs = mutableListOf<String>()
                        if (imgsArr != null) {
                            for (j in 0 until imgsArr.length()) {
                                imgs.add(imgsArr.getString(j))
                            }
                        }
                        detectedList.add(
                            Star(
                                id = o.optString("id", "$i"),
                                name = o.optString("name", "Obiekt $i"),
                                type = o.optString("type", "celestial_object"),
                                magnitude = o.optDouble("magnitude", 15.0).toFloat(),
                                raDeg = o.optDouble("ra", 0.0),
                                decDeg = o.optDouble("dec", 0.0),
                                description = o.optString("description", ""),
                                imageUrls = imgs
                            )
                        )
                    }
                }
            } catch (e: Exception) {
                Log.e("LoadPhotos", "Błąd parsowania JSON", e)
            }
        }

        PhotoItem(
            jpg, json, timestamp, lat, lon,
            gx, gy, gz, ax, ay, az, azim, pit, rol,
            targetRa, targetDec, detectedList
        )
    }
}

// --------------------------------------------------------------------------
// Komunikacja z serwerem Python (/api/catalog/...)
// --------------------------------------------------------------------------
private fun parseCatalogObjectsResponse(responseJson: String): List<Star> {
    val starsList = mutableListOf<Star>()
    if (responseJson.isBlank()) return starsList

    try {
        val trimmed = responseJson.trim()
        val jsonArray = if (trimmed.startsWith("{")) {
            val root = JSONObject(trimmed)
            root.optJSONArray("asteroids")
        } else if (trimmed.startsWith("[")) {
            JSONArray(trimmed)
        } else null

        if (jsonArray != null) {
            for (i in 0 until jsonArray.length()) {
                val obj = jsonArray.getJSONObject(i)
                val name = obj.optString("name", obj.optString("designation", "Obiekt $i"))
                val mag = obj.optDouble("magnitude", 15.0).toFloat()
                val desc = obj.optString("description", "Brak opisu w bazie.")
                val objType = obj.optString("object_type", "celestial_object")
                val raVal = obj.optDouble("ra", 0.0)
                val decVal = obj.optDouble("dec", 0.0)
                val sepVal = if (obj.has("sep_deg") && !obj.isNull("sep_deg")) obj.optDouble("sep_deg") else null

                val imgsArray = obj.optJSONArray("images")
                val imgUrls = mutableListOf<String>()
                if (imgsArray != null) {
                    for (j in 0 until imgsArray.length()) {
                        val imgObj = imgsArray.optJSONObject(j)
                        val url = imgObj?.optString("url", "") ?: ""
                        if (url.isNotEmpty()) imgUrls.add(url)
                    }
                }

                starsList.add(
                    Star(
                        id = obj.optString("id", "$i"),
                        name = name,
                        type = objType,
                        magnitude = mag,
                        raDeg = raVal,
                        decDeg = decVal,
                        sepDeg = sepVal,
                        description = desc,
                        imageUrls = imgUrls
                    )
                )
            }
        }
    } catch (e: Exception) {
        Log.e("API_PARSE", "Błąd parsowania JSON z /api/catalog/objects", e)
    }
    return starsList
}

/**
 * Pobiera obiekty z całego nieba dookoła użytkownika (radius = 180° od zenitu).
 * Do pliku zdjęcia zapisuje tylko obiekty widoczne w kadrze (w promieniu 35° od punktu celowania),
 * natomiast na Mapę AR przekazuje wszystkie obiekty dookoła, aby można było je oglądać obracając telefon.
 */
/**
 * Pobiera WSZYSTKIE obiekty zapisane dotychczas w bazie PostgreSQL (do 500 obiektów)
 * i otwiera mapę AR z całym zapisanym katalogiem.
 */
fun fetchAllSavedCatalogObjects(
    context: Context,
    onAllSavedReceived: (List<Star>) -> Unit
) {
    Toast.makeText(context, "Pobieram wszystkie zapisane obiekty z bazy...", Toast.LENGTH_SHORT).show()

    CoroutineScope(Dispatchers.IO).launch {
        try {
            val urlStr = "$API_URL/api/catalog/all"
            val conn = (URL(urlStr).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 30000000
                readTimeout = 30000000
                setRequestProperty("Accept", "application/json")
            }

            val jsonStr = if (conn.responseCode in 200..299) {
                conn.inputStream.bufferedReader().use { it.readText() }

            } else ""

            val allSaved = parseCatalogObjectsResponse(jsonStr)

            withContext(Dispatchers.Main) {
                Toast.makeText(
                    context,
                    "Wczytano z bazy: ${allSaved.size} obiektów!",
                    Toast.LENGTH_SHORT
                ).show()
                onAllSavedReceived(allSaved)
            }
        } catch (e: Exception) {
            Log.e("API_ALL_SAVED", "Błąd pobierania /api/catalog/all", e)
            withContext(Dispatchers.Main) {
                Toast.makeText(context, "Błąd połączenia z serwerem.", Toast.LENGTH_SHORT).show()
            }
        }
    }
}

fun queryAllSurroundingSkyObjects(
    context: Context,
    photoItem: PhotoItem,
    saveToDisk: Boolean = true,
    onAllSkyStarsReceived: (List<Star>) -> Unit
) {
    val lat = photoItem.latitude ?: 50.3
    val lon = photoItem.longitude ?: 18.8
    val azim = photoItem.azimuth ?: 0f
    val alt = photoItem.pitch ?: 45f

    val (centerRa, centerDec) = AstroMath.horizontalToEquatorial(lat, lon, azim, alt)

    Toast.makeText(
        context,
        "Skanuję niebo i pobieram z NASA (RA:${"%.1f".format(centerRa)}° Dec:${"%.1f".format(centerDec)}°)...",
        Toast.LENGTH_SHORT
    ).show()

    CoroutineScope(Dispatchers.IO).launch {
        try {
            // Szerszy promień (15 stopni) + wymuszone dociąganie z NASA (always_fetch_nasa=true)
            val scanUrl = String.format(
                Locale.US,
                "%s/api/catalog/scan-or-fetch?ra=%.5f&dec=%.5f&radius=15.0&lat=%.5f&lon=%.5f&always_fetch_nasa=false",
                API_URL, centerRa, centerDec, lat, lon
            )
            Log.d("API_SCAN", "GET $scanUrl")

            val scanConn = (URL(scanUrl).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 90000
                readTimeout = 90000
                setRequestProperty("Accept", "application/json")
            }

            val scanJson = if (scanConn.responseCode in 200..299) {
                scanConn.inputStream.bufferedReader().use { it.readText() }

            } else ""

            val sectorStars = parseCatalogObjectsResponse(scanJson)
                .filter { star ->
                    AstroMath.angularSeparationDeg(centerRa, centerDec, star.raDeg, star.decDeg) <= 15.0
                }
                .sortedBy { star ->
                    AstroMath.angularSeparationDeg(centerRa, centerDec, star.raDeg, star.decDeg)
                }

            if (saveToDisk && photoItem.imageFile.exists()) {
                val updatedPhoto = photoItem.copy(
                    targetRa = centerRa,
                    targetDec = centerDec,
                    detectedObjects = sectorStars
                )
                savePhotoMetadata(updatedPhoto)
            }

            withContext(Dispatchers.Main) {
                val infoMsg = if (sectorStars.isEmpty()) {
                    "Brak obiektów w tym wycinku nieba."
                } else {
                    "Znaleziono w sektorze: ${sectorStars.size} obiektów!"
                }
                Toast.makeText(context, infoMsg, Toast.LENGTH_LONG).show()
                onAllSkyStarsReceived(sectorStars)
            }

        } catch (e: Exception) {
            Log.e("API_SCAN", "Błąd skanowania nieba", e)
            withContext(Dispatchers.Main) {
                Toast.makeText(context, "Błąd połączenia z serwerem / NASA.", Toast.LENGTH_SHORT).show()
                onAllSkyStarsReceived(emptyList())

            }
        }
    }

}

fun searchCatalogByName(
    context: Context,
    query: String,
    onResult: (List<Star>) -> Unit
) {
    val trimmed = query.trim()
    if (trimmed.isEmpty()) return

    Toast.makeText(context, "Szukam w bazie i NASA JPL: $trimmed...", Toast.LENGTH_SHORT).show()

    CoroutineScope(Dispatchers.IO).launch {
        try {
            val encoded = java.net.URLEncoder.encode(trimmed, "UTF-8")
            val urlStr = "$API_URL/api/catalog/objects?name=$encoded&query_nasa=true"
            Log.d("SEARCH_NASA", "GET $urlStr")

            val conn = (URL(urlStr).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 25000
                readTimeout = 25000
                setRequestProperty("Accept", "application/json")
            }

            val code = conn.responseCode
            val jsonStr = if (code in 200..299) {
                conn.inputStream.bufferedReader().use { it.readText() }
            } else {
                Log.e("SEARCH_NASA", "HTTP $code")
                ""
            }

            val stars = parseCatalogObjectsResponse(jsonStr)
            withContext(Dispatchers.Main) {
                onResult(stars)
            }
        } catch (e: Exception) {
            Log.e("SEARCH_NASA", "Błąd wyszukiwania", e)
            withContext(Dispatchers.Main) {
                Toast.makeText(context, "Błąd połączenia przy wyszukiwaniu: ${e.message}", Toast.LENGTH_SHORT).show()
                onResult(emptyList())
            }
        }
    }
}

fun fetchCatalogObjectDetails(
    name: String,
    onResult: (description: String, imageUrls: List<String>, ra: Double?, dec: Double?) -> Unit
) {
    CoroutineScope(Dispatchers.IO).launch {
        try {
            val encoded = Uri.encode(name.trim())
            val urlString = "$API_URL/api/catalog/objects/details?name=$encoded"
            val connection = (URL(urlString).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 30000
                readTimeout = 30000
                setRequestProperty("Accept", "application/json")
            }

            if (connection.responseCode in 200..299) {
                val responseJson = connection.inputStream.bufferedReader().use { it.readText() }
                val root = JSONObject(responseJson)

                val obj = if (root.has("asteroids")) {
                    root.optJSONArray("asteroids")?.optJSONObject(0) ?: root
                } else {
                    root
                }

                val desc = obj.optString("description", "Brak opisu dla tego obiektu.")
                val raVal = if (obj.has("ra") && !obj.isNull("ra")) obj.optDouble("ra") else null
                val decVal = if (obj.has("dec") && !obj.isNull("dec")) obj.optDouble("dec") else null

                val imagesArray = obj.optJSONArray("images") ?: JSONArray()
                val urls = mutableListOf<String>()
                for (i in 0 until imagesArray.length()) {
                    val imgObj = imagesArray.optJSONObject(i)
                    val u = imgObj?.optString("url", "") ?: imagesArray.optString(i, "")
                    if (u.isNotEmpty()) urls.add(u)
                }

                withContext(Dispatchers.Main) {
                    onResult(desc, urls, raVal, decVal)
                }
            }
        } catch (e: Exception) {
            Log.e("API_CATALOG", "Błąd pobierania szczegółów obiektu", e)
        }
    }
}
/**
 * Oblicza obiektywny Azymut i Wysokość (Altitude) tylnej kamery telefonu względem Północy Geograficznej.
 * Naprawia błąd, w którym zrobienie zdjęcia podawało ujemną wysokość (pod ziemią).
 */
fun computeTrueNorthCameraAzimuthAndAltitude(
    rotationVector: FloatArray,
    lat: Double,
    lon: Double,
    altMeters: Double = 250.0
): Pair<Float, Float> {
    val magneticMatrix = FloatArray(9)
    SensorManager.getRotationMatrixFromVector(magneticMatrix, rotationVector)

    val geoField = android.hardware.GeomagneticField(
        lat.toFloat(),
        lon.toFloat(),
        altMeters.toFloat(),
        System.currentTimeMillis()
    )
    val declRad = Math.toRadians(geoField.declination.toDouble())
    val cosD = cos(declRad).toFloat()
    val sinD = sin(declRad).toFloat()

    val trueMatrix = FloatArray(9)
    trueMatrix[0] = cosD * magneticMatrix[0] - sinD * magneticMatrix[3]
    trueMatrix[1] = cosD * magneticMatrix[1] - sinD * magneticMatrix[4]
    trueMatrix[2] = cosD * magneticMatrix[2] - sinD * magneticMatrix[5]
    trueMatrix[3] = sinD * magneticMatrix[0] + cosD * magneticMatrix[3]
    trueMatrix[4] = sinD * magneticMatrix[1] + cosD * magneticMatrix[4]
    trueMatrix[5] = sinD * magneticMatrix[2] + cosD * magneticMatrix[5]
    trueMatrix[6] = magneticMatrix[6]
    trueMatrix[7] = magneticMatrix[7]
    trueMatrix[8] = magneticMatrix[8]

    val remapped = FloatArray(9)
    SensorManager.remapCoordinateSystem(
        trueMatrix,
        SensorManager.AXIS_X,
        SensorManager.AXIS_Z,
        remapped
    )

    val orientation = FloatArray(3)
    SensorManager.getOrientation(remapped, orientation)

    val trueAzimuth = (Math.toDegrees(orientation[0].toDouble()).toFloat() + 360f) % 360f
    val trueAltitude = -Math.toDegrees(orientation[1].toDouble()).toFloat()

    return Pair(trueAzimuth, trueAltitude)
}
// --------------------------------------------------------------------------
// Ekrany UI (Compose)
// --------------------------------------------------------------------------
@Composable
fun GalaxyPortalScreen(onEnterSpace: () -> Unit) {
    var isWarping by remember { mutableStateOf(false) }
    val scale by animateFloatAsState(
        targetValue = if (isWarping) 25f else 1f,
        animationSpec = tween(durationMillis = 1200),
        finishedListener = { onEnterSpace() },
        label = "scale"
    )
    val alpha by animateFloatAsState(
        targetValue = if (isWarping) 0f else 1f,
        animationSpec = tween(durationMillis = 1000),
        label = "alpha"
    )

    val infiniteTransition = rememberInfiniteTransition(label = "galaxy")
    infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(
            animation = tween(20000, easing = LinearEasing),
            repeatMode = RepeatMode.Restart
        ),
        label = "rotation"
    )

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(SpaceBlack)
            .graphicsLayer(scaleX = scale, scaleY = scale, alpha = alpha),
        contentAlignment = Alignment.Center
    ) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            val center = this.center
            val maxRadius = size.maxDimension
            val random = java.util.Random(77)
            repeat(250) {
                val x = random.nextFloat() * size.width
                val y = random.nextFloat() * size.height
                val radius = random.nextFloat() * 3f + 0.5f
                val starAlpha = random.nextFloat() * 0.9f + 0.1f
                drawCircle(color = StarWhite.copy(alpha = starAlpha), radius = radius, center = Offset(x, y))
            }
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(CosmicBlue.copy(alpha = 0.5f), NebulaPurple.copy(alpha = 0.3f), Color.Transparent),
                    center = center,
                    radius = maxRadius * 0.7f
                ),
                radius = maxRadius * 0.7f,
                center = center
            )
        }

        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
            modifier = Modifier.padding(24.dp)
        ) {
            Text(
                text = "NASA SPACE APPS",
                style = MaterialTheme.typography.headlineLarge,
                color = CosmicBlue,
                textAlign = TextAlign.Center
            )
            Spacer(modifier = Modifier.height(12.dp))
            Text(
                text = "Eksplorator Asteroid i Ciał Niebieskich",
                style = MaterialTheme.typography.titleMedium,
                color = StarWhite.copy(alpha = 0.85f),
                textAlign = TextAlign.Center
            )
            Spacer(modifier = Modifier.height(64.dp))
            Button(
                onClick = { isWarping = true },
                colors = ButtonDefaults.buttonColors(containerColor = CosmicBlue),
                shape = RoundedCornerShape(32.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .height(60.dp)
            ) {
                Text(
                    text = "WEJDŹ DO GALAKTYKI",
                    color = SpaceBlack,
                    style = MaterialTheme.typography.titleMedium
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun StarMapScreen(
    stars: List<Star>,
    onBack: () -> Unit
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val cameraProviderFuture = remember { ProcessCameraProvider.getInstance(context) }
    val executor = remember { ContextCompat.getMainExecutor(context) }

    var cameraControl by remember { mutableStateOf<androidx.camera.core.CameraControl?>(null) }
    var zoomRatio by remember { mutableFloatStateOf(1f) }
    var maxZoomRatio by remember { mutableFloatStateOf(8f) }

    var searchQuery by remember { mutableStateOf("") }
    var activeStars by remember { mutableStateOf(stars) }
    var selectedStar by remember { mutableStateOf<Star?>(null) }

    // Aktywny cel wyszukiwania, do którego prowadzi strzałka kierunkowa
    var searchTargetStar by remember { mutableStateOf<Star?>(null) }

    var onlyImportant by remember { mutableStateOf(true) }
    var visibleCount by remember { mutableStateOf(0) }

    var currentLat by remember { mutableStateOf(50.3) }
    var currentLon by remember { mutableStateOf(18.8) }
    var currentAltMeters by remember { mutableStateOf(250.0) }
    var sensorAccuracy by remember { mutableStateOf(SensorManager.SENSOR_STATUS_ACCURACY_HIGH) }

    var trueNorthRotationMatrix by remember {
        mutableStateOf(floatArrayOf(1f, 0f, 0f, 0f, 1f, 0f, 0f, 0f, 1f))
    }

    var baseCameraFovH by remember { mutableFloatStateOf(66f) }
    var baseCameraFovV by remember { mutableFloatStateOf(84f) }

    val latestHitTargets = remember { mutableListOf<Pair<Star, androidx.compose.ui.geometry.Rect>>() }

    LaunchedEffect(stars) {
        activeStars = stars
    }

    // Wyszukany obiekt (searchTargetStar) zawsze trafia na sam szczyt listy priorytetów,
    // dzięki czemu nigdy nie jest odfiltrowywany i zawsze ma widoczną etykietę!
    val prioritizedStars = remember(activeStars, searchTargetStar) {
        val baseList = if (searchTargetStar != null && activeStars.none { it.name.equals(searchTargetStar!!.name, ignoreCase = true) }) {
            listOf(searchTargetStar!!) + activeStars
        } else {
            activeStars
        }

        baseList.sortedWith(
            compareByDescending<Star> { searchTargetStar != null && it.name.equals(searchTargetStar!!.name, ignoreCase = true) }
                .thenByDescending { it.type.equals("planet", ignoreCase = true) }
                .thenByDescending { it.imageUrls.isNotEmpty() }
                .thenByDescending { it.description.startsWith("Wyróżniony obiekt") }
                .thenBy { if (it.magnitude.isNaN()) 15.0f else it.magnitude }
        )
    }

    LaunchedEffect(context) {
        try {
            val camManager = context.getSystemService(Context.CAMERA_SERVICE) as android.hardware.camera2.CameraManager
            for (camId in camManager.cameraIdList) {
                val chars = camManager.getCameraCharacteristics(camId)
                val facing = chars.get(android.hardware.camera2.CameraCharacteristics.LENS_FACING)
                if (facing == android.hardware.camera2.CameraCharacteristics.LENS_FACING_BACK) {
                    val focalLengths = chars.get(android.hardware.camera2.CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS)
                    val sensorSize = chars.get(android.hardware.camera2.CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE)
                    if (focalLengths != null && focalLengths.isNotEmpty() && sensorSize != null) {
                        val f = focalLengths[0]
                        baseCameraFovH = Math.toDegrees(2.0 * kotlin.math.atan((sensorSize.height / (2.0 * f)).toDouble())).toFloat()
                        baseCameraFovV = Math.toDegrees(2.0 * kotlin.math.atan((sensorSize.width / (2.0 * f)).toDouble())).toFloat()
                    }
                    break
                }
            }
        } catch (e: Exception) {
            Log.e("CameraFOV", "Błąd odczytu FOV", e)
        }
    }

    fun openStarDetails(star: Star) {
        selectedStar = star
        fetchCatalogObjectDetails(star.name) { desc, urls, ra, dec ->
            val updated = star.copy(
                description = desc.ifBlank { star.description },
                imageUrls = if (urls.isNotEmpty()) urls else star.imageUrls,
                raDeg = ra ?: star.raDeg,
                decDeg = dec ?: star.decDeg
            )
            selectedStar = updated
            if (searchTargetStar?.name.equals(updated.name, ignoreCase = true)) {
                searchTargetStar = updated
            }
        }
    }

    fun performSearch(query: String) {
        if (query.isBlank()) return
        searchCatalogByName(context, query) { newStars ->
            if (newStars.isNotEmpty()) {
                val target = newStars.first()
                searchTargetStar = target
                // Łączymy znaleziony obiekt z dotychczasową listą, aby zachować kontekst nieba
                val merged = (newStars + stars).distinctBy { it.name.lowercase() }
                activeStars = merged
                openStarDetails(target)
            } else {
                Toast.makeText(context, "Nie znaleziono obiektu: $query", Toast.LENGTH_SHORT).show()
            }
        }
    }

    DisposableEffect(context) {
        val fusedLocationClient = LocationServices.getFusedLocationProviderClient(context)
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED) {
            fusedLocationClient.lastLocation.addOnSuccessListener { loc ->
                if (loc != null) {
                    currentLat = loc.latitude
                    currentLon = loc.longitude
                    currentAltMeters = loc.altitude
                }
            }
        }

        val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
        val rotSensor = sensorManager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)

        val listener = object : SensorEventListener {
            override fun onSensorChanged(event: SensorEvent) {
                if (event.sensor.type == Sensor.TYPE_ROTATION_VECTOR) {
                    val magneticMatrix = FloatArray(9)
                    SensorManager.getRotationMatrixFromVector(magneticMatrix, event.values)

                    val geoField = android.hardware.GeomagneticField(
                        currentLat.toFloat(),
                        currentLon.toFloat(),
                        currentAltMeters.toFloat(),
                        System.currentTimeMillis()
                    )
                    val declRad = Math.toRadians(geoField.declination.toDouble())
                    val cosD = cos(declRad).toFloat()
                    val sinD = sin(declRad).toFloat()

                    val corrected = FloatArray(9)
                    corrected[0] = cosD * magneticMatrix[0] - sinD * magneticMatrix[3]
                    corrected[1] = cosD * magneticMatrix[1] - sinD * magneticMatrix[4]
                    corrected[2] = cosD * magneticMatrix[2] - sinD * magneticMatrix[5]

                    corrected[3] = sinD * magneticMatrix[0] + cosD * magneticMatrix[3]
                    corrected[4] = sinD * magneticMatrix[1] + cosD * magneticMatrix[4]
                    corrected[5] = sinD * magneticMatrix[2] + cosD * magneticMatrix[5]

                    corrected[6] = magneticMatrix[6]
                    corrected[7] = magneticMatrix[7]
                    corrected[8] = magneticMatrix[8]

                    trueNorthRotationMatrix = corrected
                }
            }

            override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {
                sensorAccuracy = accuracy
            }
        }

        rotSensor?.let { sensorManager.registerListener(listener, it, SensorManager.SENSOR_DELAY_GAME) }
        onDispose { sensorManager.unregisterListener(listener) }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(
                            text = if (searchTargetStar != null) "CEL: ${searchTargetStar!!.name}" else "MAPA AR ($visibleCount / ${activeStars.size})",
                            color = if (searchTargetStar != null) Color.Cyan else CosmicBlue,
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.Bold
                        )
                        Text(
                            text = "Zoom: %.1fx | Dotknij obiektu po szczegóły".format(zoomRatio),
                            color = StarWhite.copy(alpha = 0.7f),
                            style = MaterialTheme.typography.labelSmall
                        )
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Wróć", tint = CosmicBlue)
                    }
                },
                actions = {
                    Button(
                        onClick = { onlyImportant = !onlyImportant },
                        colors = ButtonDefaults.buttonColors(
                            containerColor = if (onlyImportant) CosmicBlue else SpaceDarkSurface
                        ),
                        shape = RoundedCornerShape(12.dp),
                        modifier = Modifier.padding(end = 8.dp)
                    ) {
                        Text(
                            text = if (onlyImportant) "CZYSTY" else "GĘSTY",
                            color = if (onlyImportant) SpaceBlack else CosmicBlue,
                            style = MaterialTheme.typography.labelMedium,
                            fontWeight = FontWeight.Bold
                        )
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = SpaceBlack.copy(alpha = 0.85f))
            )
        },
        containerColor = SpaceBlack
    ) { padding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .background(SpaceBlack)
                .pointerInput(maxZoomRatio) {
                    detectTransformGestures { _, _, zoomChange, _ ->
                        val newZoom = (zoomRatio * zoomChange).coerceIn(1f, maxZoomRatio)
                        zoomRatio = newZoom
                        cameraControl?.setZoomRatio(newZoom)
                    }
                }
        ) {
            AndroidView(
                factory = { ctx ->
                    PreviewView(ctx).apply {
                        layoutParams = LinearLayout.LayoutParams(
                            ViewGroup.LayoutParams.MATCH_PARENT,
                            ViewGroup.LayoutParams.MATCH_PARENT
                        )
                    }
                },
                modifier = Modifier.fillMaxSize(),
                update = { previewView ->
                    cameraProviderFuture.addListener({
                        val cameraProvider = cameraProviderFuture.get()
                        val preview = Preview.Builder().build().also {
                            it.setSurfaceProvider(previewView.surfaceProvider)
                        }
                        try {
                            cameraProvider.unbindAll()
                            val camera = cameraProvider.bindToLifecycle(
                                lifecycleOwner,
                                CameraSelector.DEFAULT_BACK_CAMERA,
                                preview
                            )
                            cameraControl = camera.cameraControl
                            maxZoomRatio = camera.cameraInfo.zoomState.value?.maxZoomRatio ?: 8f
                        } catch (exc: Exception) {
                            Log.e("StarMapScreen", "Błąd kamery", exc)
                        }
                    }, executor)
                }
            )

            Canvas(
                modifier = Modifier
                    .fillMaxSize()
                    .pointerInput(Unit) {
                        detectTapGestures { tapOffset ->
                            val snapshot = latestHitTargets.toList()
                            val directHit = snapshot.firstOrNull { (_, rect) ->
                                rect.contains(tapOffset)
                            }
                            val nearHit = snapshot.minByOrNull { (_, rect) ->
                                (rect.center - tapOffset).getDistance()
                            }?.takeIf { (_, rect) ->
                                (rect.center - tapOffset).getDistance() <= 130f
                            }

                            val chosen = directHit?.first ?: nearHit?.first
                            if (chosen != null) {
                                openStarDetails(chosen)
                            }
                        }
                    }
            ) {
                val width = size.width
                val height = size.height
                val centerX = width / 2f
                val centerY = height / 2f

                val effectiveFovH = (baseCameraFovH / zoomRatio).coerceAtLeast(5f)
                val effectiveFovV = (baseCameraFovV / zoomRatio).coerceAtLeast(5f)

                val textPaint = android.graphics.Paint().apply {
                    color = android.graphics.Color.YELLOW
                    textSize = 34f
                    isAntiAlias = true
                    typeface = android.graphics.Typeface.DEFAULT_BOLD
                    setShadowLayer(8f, 0f, 0f, android.graphics.Color.BLACK)
                }
                val targetTextPaint = android.graphics.Paint().apply {
                    color = android.graphics.Color.CYAN
                    textSize = 36f
                    isAntiAlias = true
                    typeface = android.graphics.Typeface.DEFAULT_BOLD
                    setShadowLayer(10f, 0f, 0f, android.graphics.Color.BLACK)
                }
                val bgPaint = android.graphics.Paint().apply {
                    color = android.graphics.Color.argb(225, 10, 15, 30)
                    style = android.graphics.Paint.Style.FILL
                }
                val borderPaint = android.graphics.Paint().apply {
                    color = android.graphics.Color.argb(245, 255, 215, 0)
                    style = android.graphics.Paint.Style.STROKE
                    strokeWidth = 3f
                }
                val targetBorderPaint = android.graphics.Paint().apply {
                    color = android.graphics.Color.CYAN
                    style = android.graphics.Paint.Style.STROKE
                    strokeWidth = 4f
                }

                val acceptedPositions = mutableListOf<Offset>()
                val drawnLabelRects = mutableListOf<androidx.compose.ui.geometry.Rect>()
                val frameTargets = mutableListOf<Pair<Star, androidx.compose.ui.geometry.Rect>>()
                val nowMillis = System.currentTimeMillis()

                val minDotSeparation = if (onlyImportant) 45f else 15f
                val maxOnScreen = if (onlyImportant) 25 else 80

                var searchTargetScreenPos: Offset? = null

                for (star in prioritizedStars) {
                    if (frameTargets.size >= maxOnScreen) break

                    val isSearchedTarget = searchTargetStar != null &&
                            star.name.equals(searchTargetStar!!.name, ignoreCase = true)

                    if (!isSearchedTarget && star.raDeg == 0.0 && star.decDeg == 0.0) continue

                    val enuVec = AstroMath.equatorialToEnuVector(
                        star.raDeg, star.decDeg, currentLat, currentLon, nowMillis
                    )
                    val norm = AstroMath.projectEnuVectorToScreen(
                        enuVec = enuVec,
                        rotationMatrix = trueNorthRotationMatrix,
                        fovHorizontalDeg = effectiveFovH,
                        fovVerticalDeg = effectiveFovV
                    )

                    if (norm != null) {
                        val screenPos = Offset(norm.first * width, norm.second * height)

                        if (isSearchedTarget) {
                            searchTargetScreenPos = screenPos
                        } else if (acceptedPositions.any { (it - screenPos).getDistance() < minDotSeparation }) {
                            continue
                        }
                        acceptedPositions.add(screenPos)

                        val safeMag = if (star.magnitude.isNaN()) 15.0f else star.magnitude
                        val isFeatured = isSearchedTarget || star.imageUrls.isNotEmpty() || safeMag <= 14.0f
                        val outerRadius = when {
                            isSearchedTarget -> 44f
                            isFeatured -> 34f
                            else -> 26f
                        }

                        val ringColor = when {
                            isSearchedTarget -> Color.Cyan
                            isFeatured -> Color(0xFFFFD700)
                            else -> CosmicBlue
                        }

                        // Rysujemy punkt na niebie
                        drawCircle(
                            color = ringColor.copy(alpha = 0.35f),
                            radius = outerRadius * 1.7f,
                            center = screenPos
                        )
                        drawCircle(
                            color = ringColor,
                            radius = outerRadius,
                            center = screenPos,
                            style = Stroke(width = if (isSearchedTarget) 5f else 3.5f)
                        )
                        if (isSearchedTarget) {
                            drawCircle(
                                color = Color.Cyan.copy(alpha = 0.7f),
                                radius = outerRadius * 0.6f,
                                center = screenPos,
                                style = Stroke(width = 2.5f)
                            )
                        }
                        drawCircle(color = Color.White, radius = 8f, center = screenPos)

                        val labelText = "${star.name} (${"%.1f".format(safeMag)}m)"
                        val activePaint = if (isSearchedTarget) targetTextPaint else textPaint
                        val activeBorder = if (isSearchedTarget) targetBorderPaint else borderPaint
                        val textWidth = activePaint.measureText(labelText)
                        val textHeight = 36f

                        val placeLeft = (screenPos.x + outerRadius + textWidth + 40f) > width
                        val boxLeft = if (placeLeft) {
                            screenPos.x - outerRadius - textWidth - 32f
                        } else {
                            screenPos.x + outerRadius + 12f
                        }
                        val boxTop = screenPos.y - textHeight / 2f - 8f
                        val boxRight = boxLeft + textWidth + 20f
                        val boxBottom = boxTop + textHeight + 16f

                        val labelRect = androidx.compose.ui.geometry.Rect(boxLeft, boxTop, boxRight, boxBottom)
                        val canDrawLabel = isSearchedTarget || !drawnLabelRects.any { it.overlaps(labelRect) }

                        val hitRect = if (canDrawLabel) {
                            drawnLabelRects.add(labelRect)
                            drawContext.canvas.nativeCanvas.drawRoundRect(
                                boxLeft, boxTop, boxRight, boxBottom, 12f, 12f, bgPaint
                            )
                            drawContext.canvas.nativeCanvas.drawRoundRect(
                                boxLeft, boxTop, boxRight, boxBottom, 12f, 12f, activeBorder
                            )
                            drawContext.canvas.nativeCanvas.drawText(
                                labelText, boxLeft + 10f, boxTop + textHeight, activePaint
                            )
                            androidx.compose.ui.geometry.Rect(
                                left = minOf(screenPos.x - outerRadius - 20f, boxLeft - 10f),
                                top = minOf(screenPos.y - outerRadius - 20f, boxTop - 10f),
                                right = maxOf(screenPos.x + outerRadius + 20f, boxRight + 10f),
                                bottom = maxOf(screenPos.y + outerRadius + 20f, boxBottom + 10f)
                            )
                        } else {
                            androidx.compose.ui.geometry.Rect(
                                left = screenPos.x - outerRadius - 24f,
                                top = screenPos.y - outerRadius - 24f,
                                right = screenPos.x + outerRadius + 24f,
                                bottom = screenPos.y + outerRadius + 24f
                            )
                        }

                        frameTargets.add(Pair(star, hitRect))
                    }
                }

                latestHitTargets.clear()
                latestHitTargets.addAll(frameTargets)
                if (visibleCount != frameTargets.size) {
                    visibleCount = frameTargets.size
                }

                // Celownik na środku ekranu
                drawCircle(
                    color = CosmicBlue.copy(alpha = 0.55f),
                    radius = 18f,
                    center = Offset(centerX, centerY),
                    style = Stroke(width = 2.5f)
                )

                // =========================================================================
                // STRZAŁKA KIERUNKOWA PROWADZĄCA DO WYSZUKANEGO OBIEKTU (np. Bennu)
                // =========================================================================
                val guideTarget = searchTargetStar
                    ?: selectedStar
                    ?: prioritizedStars.firstOrNull { !(it.raDeg == 0.0 && it.decDeg == 0.0) }

                if (guideTarget != null) {
                    val enuTarget = AstroMath.equatorialToEnuVector(
                        guideTarget.raDeg, guideTarget.decDeg, currentLat, currentLon, nowMillis
                    )
                    // Transformacja wektora celu z układu świata (ENU) do układu telefonu
                    val devX = trueNorthRotationMatrix[0] * enuTarget[0] + trueNorthRotationMatrix[3] * enuTarget[1] + trueNorthRotationMatrix[6] * enuTarget[2]
                    val devY = trueNorthRotationMatrix[1] * enuTarget[0] + trueNorthRotationMatrix[4] * enuTarget[1] + trueNorthRotationMatrix[7] * enuTarget[2]
                    val devZ = trueNorthRotationMatrix[2] * enuTarget[0] + trueNorthRotationMatrix[5] * enuTarget[1] + trueNorthRotationMatrix[8] * enuTarget[2]

                    // Kąt kątowy od osi patrzenia tylnej kamery (-Z)
                    val forward = (-devZ).coerceIn(-1f, 1f)
                    val angularDistDeg = Math.toDegrees(kotlin.math.acos(forward.toDouble())).toInt()

                    // Rysujemy strzałkę zawsze, gdy obiekt jest poza ekranem lub dalej niż 120px od celownika
                    val onScreenOffset = searchTargetScreenPos
                    val distFromCenterPx = if (onScreenOffset != null) {
                        (onScreenOffset - Offset(centerX, centerY)).getDistance()
                    } else {
                        9999f
                    }

                    if (distFromCenterPx > 120f) {
                        val angle = atan2((-devY).toDouble(), devX.toDouble()).toFloat()
                        val startDist = 42f
                        val arrowRadius = 240f

                        val startX = centerX + cos(angle) * startDist
                        val startY = centerY + sin(angle) * startDist
                        val tipX = centerX + cos(angle) * arrowRadius
                        val tipY = centerY + sin(angle) * arrowRadius

                        val arrowColor = if (searchTargetStar != null) Color.Cyan else Color(0xFFFFD700)

                        // Linia prowadząca od celownika
                        drawLine(
                            color = arrowColor.copy(alpha = 0.85f),
                            start = Offset(startX, startY),
                            end = Offset(tipX, tipY),
                            strokeWidth = 6f
                        )

                        // Grot strzałki (trójkąt wskazujący kierunek obrotu telefonu)
                        val headLength = 34f
                        val headAngle = Math.toRadians(28.0).toFloat()
                        val leftWingX = tipX - headLength * cos(angle - headAngle)
                        val leftWingY = tipY - headLength * sin(angle - headAngle)
                        val rightWingX = tipX - headLength * cos(angle + headAngle)
                        val rightWingY = tipY - headLength * sin(angle + headAngle)

                        val arrowHeadPath = androidx.compose.ui.graphics.Path().apply {
                            moveTo(tipX, tipY)
                            lineTo(leftWingX, leftWingY)
                            lineTo(rightWingX, rightWingY)
                            close()
                        }
                        drawPath(path = arrowHeadPath, color = arrowColor)

                        // Etykieta przy grocie strzałki z nazwą celu i odległością w stopniach
                        if (searchTargetStar != null) {
                            val hintText = "${guideTarget.name} • ${angularDistDeg}°"
                            val hintWidth = targetTextPaint.measureText(hintText)
                            val hintX = (tipX - hintWidth / 2f).coerceIn(24f, width - hintWidth - 24f)
                            val hintY = (tipY + if (sin(angle) >= 0) 48f else -24f).coerceIn(180f, height - 180f)

                            drawContext.canvas.nativeCanvas.drawRoundRect(
                                hintX - 12f, hintY - 34f, hintX + hintWidth + 12f, hintY + 12f, 10f, 10f, bgPaint
                            )
                            drawContext.canvas.nativeCanvas.drawText(hintText, hintX, hintY, targetTextPaint)
                        }
                    }
                }
            }

            // Pasek wyszukiwania na górze
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(12.dp)
                    .align(Alignment.TopCenter)
            ) {
                Surface(
                    color = SpaceDarkSurface.copy(alpha = 0.95f),
                    shape = RoundedCornerShape(24.dp),
                    border = androidx.compose.foundation.BorderStroke(
                        1.5.dp,
                        if (searchTargetStar != null) Color.Cyan else CosmicBlue
                    ),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 8.dp, vertical = 2.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Icon(
                            imageVector = Icons.Default.Search,
                            contentDescription = "Szukaj",
                            tint = if (searchTargetStar != null) Color.Cyan else CosmicBlue,
                            modifier = Modifier.padding(start = 6.dp, end = 4.dp)
                        )

                        OutlinedTextField(
                            value = searchQuery,
                            onValueChange = { searchQuery = it },
                            placeholder = { Text("Szukaj w katalogu (np. Bennu)...", color = StarWhite.copy(alpha = 0.5f)) },
                            singleLine = true,
                            colors = TextFieldDefaults.colors(
                                focusedContainerColor = Color.Transparent,
                                unfocusedContainerColor = Color.Transparent,
                                focusedIndicatorColor = Color.Transparent,
                                unfocusedIndicatorColor = Color.Transparent,
                                focusedTextColor = StarWhite,
                                unfocusedTextColor = StarWhite
                            ),
                            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                            keyboardActions = KeyboardActions(
                                onSearch = { performSearch(searchQuery) }
                            ),
                            modifier = Modifier.weight(1f)
                        )

                        if (searchQuery.isNotEmpty() || searchTargetStar != null) {
                            IconButton(onClick = {
                                searchQuery = ""
                                searchTargetStar = null
                                activeStars = stars
                            }) {
                                Icon(Icons.Default.Close, contentDescription = "Wyczyść cel", tint = StarWhite.copy(alpha = 0.8f))
                            }
                        }

                        Button(
                            onClick = { performSearch(searchQuery) },
                            colors = ButtonDefaults.buttonColors(
                                containerColor = if (searchTargetStar != null) Color.Cyan else CosmicBlue
                            ),
                            shape = RoundedCornerShape(16.dp)
                        ) {
                            Text("SZUKAJ", color = SpaceBlack, fontWeight = FontWeight.Bold)
                        }
                    }
                }
            }

            // Dolny suwak Zoomu na Mapie AR (1.0x .. maxZoom)
            Surface(
                color = SpaceBlack.copy(alpha = 0.8f),
                shape = RoundedCornerShape(20.dp),
                border = androidx.compose.foundation.BorderStroke(1.dp, CosmicBlue.copy(alpha = 0.5f)),
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 14.dp)
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.padding(horizontal = 14.dp, vertical = 4.dp)
                ) {
                    Text(
                        text = "%.1fx".format(zoomRatio),
                        color = CosmicBlue,
                        style = MaterialTheme.typography.labelLarge,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.width(48.dp)
                    )
                    Slider(
                        value = zoomRatio,
                        onValueChange = { newVal ->
                            zoomRatio = newVal
                            cameraControl?.setZoomRatio(newVal)
                        },
                        valueRange = 1f..maxZoomRatio,
                        colors = SliderDefaults.colors(
                            thumbColor = CosmicBlue,
                            activeTrackColor = CosmicBlue,
                            inactiveTrackColor = SpaceDarkSurface
                        ),
                        modifier = Modifier.weight(1f)
                    )
                    if (zoomRatio > 1.05f) {
                        TextButton(onClick = {
                            zoomRatio = 1f
                            cameraControl?.setZoomRatio(1f)
                        }) {
                            Text("1x", color = StarWhite, style = MaterialTheme.typography.labelMedium)
                        }
                    }
                }
            }

            // Karta informacji po kliknięciu punktu
            selectedStar?.let { star ->
                AlertDialog(
                    onDismissRequest = { selectedStar = null },
                    confirmButton = {
                        Button(
                            onClick = { selectedStar = null },
                            colors = ButtonDefaults.buttonColors(containerColor = CosmicBlue)
                        ) {
                            Text("ZAMKNIJ", color = SpaceBlack, fontWeight = FontWeight.Bold)
                        }
                    },
                    title = {
                        Column {
                            Text(
                                text = "Szczegóły obiektu",
                                color = StarWhite.copy(alpha = 0.6f),
                                style = MaterialTheme.typography.labelMedium
                            )
                            Text(
                                text = "Nazwa: ${star.name}",
                                color = CosmicBlue,
                                style = MaterialTheme.typography.titleLarge,
                                fontWeight = FontWeight.Bold
                            )
                        }
                    },
                    text = {
                        Column(modifier = Modifier.verticalScroll(rememberScrollState())) {
                            Surface(
                                color = SpaceBlack.copy(alpha = 0.6f),
                                shape = RoundedCornerShape(12.dp),
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                Column(modifier = Modifier.padding(10.dp)) {
                                    Text(
                                        text = "Nazwa: ${star.name}",
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = StarWhite,
                                        fontWeight = FontWeight.Bold
                                    )
                                    Text(
                                        text = "Typ obiektu: ${star.type}",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = NebulaPurple
                                    )
                                    Spacer(modifier = Modifier.height(6.dp))
                                    Text(
                                        text = "Rektascensja (RA): %.4f°".format(star.raDeg),
                                        style = MaterialTheme.typography.bodySmall,
                                        color = CosmicBlue
                                    )
                                    Text(
                                        text = "Deklinacja (Dec): %.4f°".format(star.decDeg),
                                        style = MaterialTheme.typography.bodySmall,
                                        color = CosmicBlue
                                    )
                                    Text(
                                        text = "Jasność obserwowana: ${if (star.magnitude.isNaN()) "15.0" else "%.1f".format(star.magnitude)} mag",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = Color(0xFFFFD700)
                                    )
                                }
                            }

                            Spacer(modifier = Modifier.height(10.dp))
                            Text(
                                text = "Opis:",
                                style = MaterialTheme.typography.labelMedium,
                                color = CosmicBlue,
                                fontWeight = FontWeight.Bold
                            )
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = star.description.ifEmpty { "Brak opisu w bazie." },
                                style = MaterialTheme.typography.bodyMedium,
                                color = StarWhite
                            )

                            if (star.imageUrls.isNotEmpty()) {
                                Spacer(modifier = Modifier.height(10.dp))
                                Text(
                                    text = "Powiązane obrazy / dane (${star.imageUrls.size}):",
                                    style = MaterialTheme.typography.labelMedium,
                                    color = NebulaPurple,
                                    fontWeight = FontWeight.Bold
                                )
                                star.imageUrls.forEach { url ->
                                    Text(
                                        text = "• $url",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = CosmicBlue,
                                        modifier = Modifier.padding(top = 2.dp)
                                    )
                                }
                            }
                        }
                    },
                    containerColor = SpaceDarkSurface,
                    titleContentColor = CosmicBlue,
                    textContentColor = StarWhite
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CameraView(
    outputDirectory: File,
    onPhotoCaptured: (PhotoItem) -> Unit,
    onStarsReceived: (List<Star>) -> Unit,
    onOpenGallery: () -> Unit,
    photoCount: Int
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val cameraProviderFuture = remember { ProcessCameraProvider.getInstance(context) }
    var imageCapture by remember { mutableStateOf<ImageCapture?>(null) }
    var cameraControl by remember { mutableStateOf<androidx.camera.core.CameraControl?>(null) }
    var cameraInfo by remember { mutableStateOf<androidx.camera.core.CameraInfo?>(null) }
    val executor = remember { ContextCompat.getMainExecutor(context) }

    // Stan przybliżenia (Zoom) aparatu
    var zoomRatio by remember { mutableFloatStateOf(1f) }
    var maxZoomRatio by remember { mutableFloatStateOf(8f) }

    var currentLat by remember { mutableStateOf<Double?>(null) }
    var currentLon by remember { mutableStateOf<Double?>(null) }
    var currentAltMeters by remember { mutableStateOf(250.0) }
    var azimuth by remember { mutableFloatStateOf(0f) }
    var altitude by remember { mutableFloatStateOf(0f) }
    var roll by remember { mutableFloatStateOf(0f) }

    var accelX by remember { mutableFloatStateOf(0f) }
    var accelY by remember { mutableFloatStateOf(0f) }
    var accelZ by remember { mutableFloatStateOf(0f) }
    var gyroX by remember { mutableFloatStateOf(0f) }
    var gyroY by remember { mutableFloatStateOf(0f) }
    var gyroZ by remember { mutableFloatStateOf(0f) }

    val liveSensorState = remember {
        object {
            var lat: Double? = null
            var lon: Double? = null
            var az: Float = 0f
            var alt: Float = 0f
            var rl: Float = 0f
            var ax: Float = 0f
            var ay: Float = 0f
            var azc: Float = 0f
            var gx: Float = 0f
            var gy: Float = 0f
            var gz: Float = 0f
        }
    }

    DisposableEffect(context) {
        val fusedLocationClient = LocationServices.getFusedLocationProviderClient(context)
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED) {
            fusedLocationClient.lastLocation.addOnSuccessListener { location ->
                if (location != null) {
                    currentLat = location.latitude
                    currentLon = location.longitude
                    currentAltMeters = location.altitude
                    liveSensorState.lat = location.latitude
                    liveSensorState.lon = location.longitude
                }
            }
        }

        val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
        val rotationSensor = sensorManager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)
        val accelSensor = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
        val gyroSensor = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)

        val sensorListener = object : SensorEventListener {
            override fun onSensorChanged(event: SensorEvent) {
                when (event.sensor.type) {
                    Sensor.TYPE_ROTATION_VECTOR -> {
                        val lat = currentLat ?: 50.3
                        val lon = currentLon ?: 18.8
                        val (trueAz, trueAlt) = computeTrueNorthCameraAzimuthAndAltitude(
                            rotationVector = event.values,
                            lat = lat,
                            lon = lon,
                            altMeters = currentAltMeters
                        )
                        azimuth = trueAz
                        altitude = trueAlt
                        liveSensorState.az = trueAz
                        liveSensorState.alt = trueAlt

                        val rotMat = FloatArray(9)
                        SensorManager.getRotationMatrixFromVector(rotMat, event.values)
                        val ori = FloatArray(3)
                        SensorManager.getOrientation(rotMat, ori)
                        val rDeg = Math.toDegrees(ori[2].toDouble()).toFloat()
                        roll = rDeg
                        liveSensorState.rl = rDeg
                    }
                    Sensor.TYPE_ACCELEROMETER -> {
                        accelX = event.values[0]
                        accelY = event.values[1]
                        accelZ = event.values[2]
                        liveSensorState.ax = accelX
                        liveSensorState.ay = accelY
                        liveSensorState.azc = accelZ
                    }
                    Sensor.TYPE_GYROSCOPE -> {
                        gyroX = event.values[0]
                        gyroY = event.values[1]
                        gyroZ = event.values[2]
                        liveSensorState.gx = gyroX
                        liveSensorState.gy = gyroY
                        liveSensorState.gz = gyroZ
                    }
                }
            }

            override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
        }

        rotationSensor?.let { sensorManager.registerListener(sensorListener, it, SensorManager.SENSOR_DELAY_GAME) }
        accelSensor?.let { sensorManager.registerListener(sensorListener, it, SensorManager.SENSOR_DELAY_UI) }
        gyroSensor?.let { sensorManager.registerListener(sensorListener, it, SensorManager.SENSOR_DELAY_UI) }

        onDispose {
            sensorManager.unregisterListener(sensorListener)
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    // Kliknięcie w COSMIC EXPLORER otwiera mapę wszystkich zapisanych obiektów z bazy
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.clickable {
                            fetchAllSavedCatalogObjects(context) { allSavedStars ->
                                onStarsReceived(allSavedStars)
                            }
                        }
                    ) {
                        Text(
                            text = "COSMIC EXPLORER",
                            color = CosmicBlue,
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Surface(
                            color = CosmicBlue.copy(alpha = 0.2f),
                            shape = RoundedCornerShape(8.dp),
                            border = androidx.compose.foundation.BorderStroke(1.dp, CosmicBlue)
                        ) {
                            Text(
                                text = "WSZYSTKIE",
                                color = CosmicBlue,
                                style = MaterialTheme.typography.labelSmall,
                                modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                            )
                        }
                    }
                },
                actions = {
                    Button(
                        onClick = onOpenGallery,
                        colors = ButtonDefaults.buttonColors(containerColor = SpaceDarkSurface),
                        shape = RoundedCornerShape(12.dp),
                        modifier = Modifier.padding(end = 8.dp)
                    ) {
                        Text("GALERIA ($photoCount)", color = CosmicBlue)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = SpaceBlack.copy(alpha = 0.85f))
            )
        },
        containerColor = SpaceBlack
    ) { paddingValues ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                // Obsługa gestu szczypania dwoma palcami (Pinch-to-Zoom)
                .pointerInput(maxZoomRatio) {
                    detectTransformGestures { _, _, zoomChange, _ ->
                        val newZoom = (zoomRatio * zoomChange).coerceIn(1f, maxZoomRatio)
                        zoomRatio = newZoom
                        cameraControl?.setZoomRatio(newZoom)
                    }
                }
        ) {
            AndroidView(
                factory = { ctx ->
                    PreviewView(ctx).apply {
                        layoutParams = LinearLayout.LayoutParams(
                            ViewGroup.LayoutParams.MATCH_PARENT,
                            ViewGroup.LayoutParams.MATCH_PARENT
                        )
                    }
                },
                modifier = Modifier.fillMaxSize(),
                update = { previewView ->
                    cameraProviderFuture.addListener({
                        val cameraProvider = cameraProviderFuture.get()
                        val preview = Preview.Builder().build().also {
                            it.setSurfaceProvider(previewView.surfaceProvider)
                        }
                        imageCapture = ImageCapture.Builder().build()
                        try {
                            cameraProvider.unbindAll()
                            val camera = cameraProvider.bindToLifecycle(
                                lifecycleOwner,
                                CameraSelector.DEFAULT_BACK_CAMERA,
                                preview,
                                imageCapture
                            )
                            cameraControl = camera.cameraControl
                            cameraInfo = camera.cameraInfo
                            maxZoomRatio = camera.cameraInfo.zoomState.value?.maxZoomRatio ?: 8f
                        } catch (exc: Exception) {
                            Log.e("CameraView", "Błąd uruchamiania kamery", exc)
                        }
                    }, executor)
                }
            )

            // Celownik na środku ekranu (górny HUD usunięty zgodnie z prośbą)
            Canvas(modifier = Modifier.fillMaxSize()) {
                val cx = size.width / 2f
                val cy = size.height / 2f
                drawCircle(
                    color = CosmicBlue.copy(alpha = 0.65f),
                    radius = 28f,
                    center = Offset(cx, cy),
                    style = Stroke(width = 2.5f)
                )
                drawCircle(
                    color = Color(0xFFFFD700),
                    radius = 4f,
                    center = Offset(cx, cy)
                )
            }

            // Dolny panel: suwak zoomu + przyciski akcji
            Column(
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .fillMaxWidth()
                    .background(SpaceBlack.copy(alpha = 0.85f))
                    .padding(top = 8.dp, bottom = 18.dp, start = 16.dp, end = 16.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                // Suwak Zoomu (1.0x .. maxZoom)
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 8.dp)
                ) {
                    Text(
                        text = "%.1fx".format(zoomRatio),
                        color = CosmicBlue,
                        style = MaterialTheme.typography.labelMedium,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.width(44.dp)
                    )
                    Slider(
                        value = zoomRatio,
                        onValueChange = { newVal ->
                            zoomRatio = newVal
                            cameraControl?.setZoomRatio(newVal)
                        },
                        valueRange = 1f..maxZoomRatio,
                        colors = SliderDefaults.colors(
                            thumbColor = CosmicBlue,
                            activeTrackColor = CosmicBlue,
                            inactiveTrackColor = SpaceDarkSurface
                        ),
                        modifier = Modifier.weight(1f)
                    )
                    if (zoomRatio > 1.05f) {
                        TextButton(onClick = {
                            zoomRatio = 1f
                            cameraControl?.setZoomRatio(1f)
                        }) {
                            Text("1x", color = StarWhite.copy(alpha = 0.8f), style = MaterialTheme.typography.labelSmall)
                        }
                    }
                }

                Spacer(modifier = Modifier.height(6.dp))

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceEvenly,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Button(
                        onClick = {
                            val tempItem = PhotoItem(
                                imageFile = File(outputDirectory, "temp_ar.jpg"),
                                jsonFile = File(outputDirectory, "temp_ar.json"),
                                timestamp = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date()),
                                latitude = liveSensorState.lat,
                                longitude = liveSensorState.lon,
                                azimuth = liveSensorState.az,
                                pitch = liveSensorState.alt,
                                roll = liveSensorState.rl,
                                accelX = liveSensorState.ax,
                                accelY = liveSensorState.ay,
                                accelZ = liveSensorState.azc,
                                gyroX = liveSensorState.gx,
                                gyroY = liveSensorState.gy,
                                gyroZ = liveSensorState.gz
                            )
                            queryAllSurroundingSkyObjects(
                                context = context,
                                photoItem = tempItem,
                                saveToDisk = false,
                                onAllSkyStarsReceived = onStarsReceived
                            )
                        },
                        colors = ButtonDefaults.buttonColors(containerColor = SpaceDarkSurface),
                        shape = RoundedCornerShape(16.dp)
                    ) {
                        Text("SEKTOR AR", color = CosmicBlue, fontWeight = FontWeight.Bold)
                    }

                    Button(
                        onClick = {
                            val capture = imageCapture ?: return@Button
                            val stamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
                            val photoFile = File(outputDirectory, "COSMIC_$stamp.jpg")
                            val jsonFile = File(outputDirectory, "COSMIC_$stamp.json")
                            val outputOptions = ImageCapture.OutputFileOptions.Builder(photoFile).build()

                            val snapLat = liveSensorState.lat
                            val snapLon = liveSensorState.lon
                            val snapAz = liveSensorState.az
                            val snapAlt = liveSensorState.alt
                            val snapRoll = liveSensorState.rl
                            val snapAx = liveSensorState.ax
                            val snapAy = liveSensorState.ay
                            val snapAzc = liveSensorState.azc
                            val snapGx = liveSensorState.gx
                            val snapGy = liveSensorState.gy
                            val snapGz = liveSensorState.gz

                            capture.takePicture(
                                outputOptions,
                                executor,
                                object : ImageCapture.OnImageSavedCallback {
                                    override fun onImageSaved(outputFileResults: ImageCapture.OutputFileResults) {
                                        val photoItem = PhotoItem(
                                            imageFile = photoFile,
                                            jsonFile = jsonFile,
                                            timestamp = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date()),
                                            latitude = snapLat,
                                            longitude = snapLon,
                                            azimuth = snapAz,
                                            pitch = snapAlt,
                                            roll = snapRoll,
                                            accelX = snapAx,
                                            accelY = snapAy,
                                            accelZ = snapAzc,
                                            gyroX = snapGx,
                                            gyroY = snapGy,
                                            gyroZ = snapGz
                                        )
                                        savePhotoMetadata(photoItem)
                                        onPhotoCaptured(photoItem)
                                        queryAllSurroundingSkyObjects(
                                            context = context,
                                            photoItem = photoItem,
                                            saveToDisk = true,
                                            onAllSkyStarsReceived = onStarsReceived
                                        )
                                    }

                                    override fun onError(exception: ImageCaptureException) {
                                        Log.e("CameraView", "Błąd zapisu zdjęcia", exception)
                                        Toast.makeText(context, "Błąd zapisu zdjęcia", Toast.LENGTH_SHORT).show()
                                    }
                                }
                            )
                        },
                        colors = ButtonDefaults.buttonColors(containerColor = CosmicBlue),
                        shape = RoundedCornerShape(50),
                        modifier = Modifier.height(60.dp)
                    ) {
                        Text("FOTO + AR", color = SpaceBlack, fontWeight = FontWeight.Bold)
                    }

                    Button(
                        onClick = onOpenGallery,
                        colors = ButtonDefaults.buttonColors(containerColor = SpaceDarkSurface),
                        shape = RoundedCornerShape(16.dp)
                    ) {
                        Text("GALERIA", color = CosmicBlue, fontWeight = FontWeight.Bold)
                    }
                }
            }
        }
    }
}
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun GalleryScreen(
    photos: List<PhotoItem>,
    onPhotoClick: (PhotoItem) -> Unit,
    onBack: () -> Unit
) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("GALERIA ZDJĘĆ (${photos.size})", color = CosmicBlue) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Wróć", tint = CosmicBlue)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = SpaceBlack)
            )
        },
        containerColor = SpaceBlack
    ) { padding ->
        LazyVerticalGrid(
            columns = GridCells.Fixed(1),
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(8.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            items(photos) { item ->
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onPhotoClick(item) },
                    colors = CardDefaults.cardColors(containerColor = SpaceDarkSurface),
                    border = androidx.compose.foundation.BorderStroke(1.dp, NebulaPurple.copy(alpha = 0.6f))
                ) {
                    Column(modifier = Modifier.padding(12.dp)) {
                        val bitmap = remember(item.imageFile) {
                            BitmapFactory.decodeFile(item.imageFile.absolutePath)
                        }
                        if (bitmap != null) {
                            Image(
                                bitmap = bitmap.asImageBitmap(),
                                contentDescription = null,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .height(200.dp),
                                contentScale = ContentScale.Crop
                            )
                        }
                        Spacer(modifier = Modifier.height(8.dp))
                        Text(text = "Data: ${item.timestamp}", style = MaterialTheme.typography.bodyMedium, color = StarWhite)

                        val gpsStr = if (item.latitude != null && item.longitude != null) {
                            "GPS: %.4f, %.4f | Azymut: %.1f°".format(item.latitude, item.longitude, item.azimuth ?: 0f)
                        } else {
                            "GPS: Brak danych"
                        }
                        Text(text = gpsStr, style = MaterialTheme.typography.bodySmall, color = CosmicBlue)

                        if (item.targetRa != null && item.targetDec != null) {
                            Text(
                                text = "Sektor zdjęcia: RA %.2f° | Dec %.2f°".format(item.targetRa, item.targetDec),
                                style = MaterialTheme.typography.bodySmall,
                                color = StarWhite.copy(alpha = 0.8f)
                            )
                        }

                        Spacer(modifier = Modifier.height(8.dp))
                        HorizontalDivider(color = CosmicBlue.copy(alpha = 0.3f))
                        Spacer(modifier = Modifier.height(6.dp))

                        if (item.detectedObjects.isEmpty()) {
                            Text(
                                text = "Brak zapisanych obiektów w kadrze (kliknij zdjęcie, aby odświeżyć).",
                                style = MaterialTheme.typography.bodySmall,
                                color = StarWhite.copy(alpha = 0.6f)
                            )
                        } else {
                            Text(
                                text = "Wykryte obiekty w kadrze zdjęcia (${item.detectedObjects.size}):",
                                style = MaterialTheme.typography.labelMedium,
                                color = NebulaPurple,
                                fontWeight = FontWeight.Bold
                            )
                            item.detectedObjects.take(3).forEach { obj ->
                                Text(
                                    text = "• ${obj.name} (${obj.type}): ${obj.description}",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = StarWhite,
                                    maxLines = 2,
                                    overflow = TextOverflow.Ellipsis,
                                    modifier = Modifier.padding(top = 2.dp)
                                )
                            }
                            if (item.detectedObjects.size > 3) {
                                Text(
                                    text = "...i ${item.detectedObjects.size - 3} więcej (kliknij, aby zobaczyć wszystkie)",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = CosmicBlue,
                                    modifier = Modifier.padding(top = 4.dp)
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PhotoDetailScreen(
    photoItem: PhotoItem,
    onBack: () -> Unit,
    onStarsReceived: (List<Star>) -> Unit,
    onDelete: (PhotoItem) -> Unit
) {
    val context = LocalContext.current
    var scale by remember { mutableFloatStateOf(1f) }
    var offsetX by remember { mutableFloatStateOf(0f) }
    var offsetY by remember { mutableFloatStateOf(0f) }
    var currentObjects by remember { mutableStateOf(photoItem.detectedObjects) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Szczegóły i Obiekty", color = CosmicBlue) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Wróć", tint = CosmicBlue)
                    }
                },
                actions = {
                    IconButton(onClick = {
                        queryAllSurroundingSkyObjects(context, photoItem, saveToDisk = true) { allStars ->
                            val lat = photoItem.latitude ?: 50.3
                            val lon = photoItem.longitude ?: 18.8
                            val (cRa, cDec) = AstroMath.horizontalToEquatorial(lat, lon, photoItem.azimuth ?: 0f, photoItem.pitch ?: 45f)
                            currentObjects = allStars.filter {
                                AstroMath.angularSeparationDeg(cRa, cDec, it.raDeg, it.decDeg) <= 35.0
                            }
                            onStarsReceived(allStars)
                        }
                    }) {
                        Icon(Icons.Default.Send, contentDescription = "Odśwież z katalogu i otwórz AR", tint = CosmicBlue)
                    }
                    IconButton(onClick = {
                        onDelete(photoItem)
                        onBack()
                    }) {
                        Icon(Icons.Default.Delete, contentDescription = "Usuń", tint = Color.Red)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = SpaceBlack)
            )
        },
        containerColor = SpaceBlack
    ) { padding ->
        val bitmap = remember(photoItem.imageFile) {
            BitmapFactory.decodeFile(photoItem.imageFile.absolutePath)
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(0.55f)
                    .pointerInput(Unit) {
                        detectTransformGestures { _, pan, zoom, _ ->
                            scale = (scale * zoom).coerceIn(1f, 5f)
                            if (scale > 1f) {
                                offsetX += pan.x
                                offsetY += pan.y
                            } else {
                                offsetX = 0f
                                offsetY = 0f
                            }
                        }
                    },
                contentAlignment = Alignment.Center
            ) {
                if (bitmap != null) {
                    Image(
                        bitmap = bitmap.asImageBitmap(),
                        contentDescription = null,
                        modifier = Modifier
                            .fillMaxSize()
                            .graphicsLayer(
                                scaleX = scale,
                                scaleY = scale,
                                translationX = offsetX,
                                translationY = offsetY
                            ),
                        contentScale = ContentScale.Fit
                    )
                }
            }

            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(0.45f),
                color = SpaceDarkSurface,
                border = androidx.compose.foundation.BorderStroke(1.dp, CosmicBlue.copy(alpha = 0.4f))
            ) {
                Column(
                    modifier = Modifier
                        .padding(16.dp)
                        .verticalScroll(rememberScrollState())
                ) {
                    Text(text = "Data: ${photoItem.timestamp}", style = MaterialTheme.typography.bodyMedium, color = StarWhite)
                    val gpsStr = if (photoItem.latitude != null && photoItem.longitude != null) {
                        "GPS: %.4f, %.4f | Azymut: %.1f° | Wysokość: %.1f°".format(
                            photoItem.latitude, photoItem.longitude, photoItem.azimuth ?: 0f, photoItem.pitch ?: 0f
                        )
                    } else "GPS: Brak danych"
                    Text(text = gpsStr, style = MaterialTheme.typography.bodySmall, color = CosmicBlue)

                    if (photoItem.targetRa != null && photoItem.targetDec != null) {
                        Text(
                            text = "Współrzędne środka kadru: RA %.4f° | Dec %.4f°".format(photoItem.targetRa, photoItem.targetDec),
                            style = MaterialTheme.typography.bodySmall,
                            color = StarWhite.copy(alpha = 0.8f)
                        )
                    }

                    Spacer(modifier = Modifier.height(10.dp))
                    HorizontalDivider(color = NebulaPurple.copy(alpha = 0.5f))
                    Spacer(modifier = Modifier.height(8.dp))

                    Text(
                        text = "OBIEKTY WIDOCZNE NA ZDJĘCIU (${currentObjects.size}):",
                        style = MaterialTheme.typography.titleSmall,
                        color = CosmicBlue
                    )
                    Spacer(modifier = Modifier.height(6.dp))

                    if (currentObjects.isEmpty()) {
                        Text(
                            text = "Brak zapisanych obiektów. Kliknij ikonę samolociku w prawym górnym rogu, aby ponownie porównać zdjęcie z bazą.",
                            style = MaterialTheme.typography.bodySmall,
                            color = StarWhite.copy(alpha = 0.7f)
                        )
                    } else {
                        currentObjects.forEach { star ->
                            Card(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(vertical = 4.dp),
                                colors = CardDefaults.cardColors(containerColor = SpaceBlack.copy(alpha = 0.6f)),
                                border = androidx.compose.foundation.BorderStroke(1.dp, CosmicBlue.copy(alpha = 0.3f))
                            ) {
                                Column(modifier = Modifier.padding(10.dp)) {
                                    Text(
                                        text = "${star.name} [${star.type}]",
                                        style = MaterialTheme.typography.titleSmall,
                                        color = Color(0xFFFFD700)
                                    )
                                    Text(
                                        text = "RA: %.4f° | Dec: %.4f° | Jasność: %.2f mag".format(
                                            star.raDeg, star.decDeg, star.magnitude
                                        ),
                                        style = MaterialTheme.typography.labelSmall,
                                        color = CosmicBlue
                                    )
                                    Spacer(modifier = Modifier.height(4.dp))
                                    Text(
                                        text = star.description,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = StarWhite
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}