# PlanetCatch

An Android mobile application that communicates with a local server written in Python.

## Prerequisites

- **Android Studio** (latest recommended version)
- **Python 3.8+**
- **A port tunneling tool** (e.g., `ngrok`, `LocalTunnel`, `Cloudflare Tunnel`, or built-in port forwarding in VS Code)

---

## 1. Running the Server (Backend)

To start the server and expose it publicly so the mobile app can connect to it, follow these steps:

1. Navigate to the `server` directory:
   ```bash
   cd server
   ```

2. Create and activate a virtual environment (`venv`):
   - **Windows:**
     ```bash
     python -m venv venv
     venv\Scripts\activate
     ```
   - **Linux / macOS:**
     ```bash
     python3 -m venv venv
     source venv/bin/activate
     ```

3. Install the required Python libraries:
   ```bash
   pip install -r requirements.txt
   ```
   > **Note:** If there is no `requirements.txt` file in the repository, manually install the required packages (e.g., `pip install fastapi uvicorn` or `pip install flask`).

4. Start the server (take note of the port number it is listening on, e.g., `8000` or `5000`):
   ```bash
   python app.py
   ```

5. Start port tunneling on the active port. Open a new terminal window and expose the local server port (below is an example using `ngrok` on port `5000`):
   ```bash
   ngrok http 5000
   ```

6. Copy the generated URL from the tunneling tool (e.g., `https://your-unique-address.ngrok-free.app`) — you will need it to configure the Android app.

---

## 2. Running the Mobile App (Android)

To properly build and run the application, you need to replace the source directory in a newly created Android Studio project:

1. Open **Android Studio** and select **New Project**.
2. Choose the **Empty Activity** template (or **Empty Views Activity**, depending on the UI framework used) and create the project.
3. Once the project loads, go to its folder on your drive (or use the **Project** view in Android Studio) and delete the entire `src` folder located inside the `app/` directory (`app/src`).
4. Copy the `src` folder from this GitHub repository (`app/src`) and paste it in place of the deleted folder (inside your new project's `app/` directory).
5. Locate where the server address (API URL) is defined in the app's source files and paste the tunneled URL generated in **Step 1.6**.
6. Click **Sync Project with Gradle Files** (the elephant icon in the top toolbar of Android Studio), then run the application on an emulator or a physical device (**Run 'app'**).
