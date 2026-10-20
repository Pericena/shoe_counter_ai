// Cámara del dispositivo (getUserMedia). Requiere contexto seguro: http://localhost o HTTPS.
export function cameraSupported() {
  return Boolean(navigator.mediaDevices && navigator.mediaDevices.getUserMedia) && window.isSecureContext;
}

export function cameraHelp() {
  if (!window.isSecureContext) {
    return "La cámara solo funciona en http://localhost o con HTTPS. Para usarla desde un móvil hay que publicar la app con HTTPS (ver docs/09).";
  }
  return "Este navegador no permite usar la cámara.";
}

export class Camera {
  constructor(video) {
    this.video = video;
    this.stream = null;
    this.facing = "environment";
  }

  async start() {
    this.stop();
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: this.facing }, width: { ideal: 1920 }, height: { ideal: 1080 } },
      audio: false,
    });
    this.video.srcObject = this.stream;
    await this.video.play();
    await new Promise((resolve) => {
      if (this.video.videoWidth) resolve();
      else this.video.addEventListener("loadedmetadata", resolve, { once: true });
    });
  }

  async switch() {
    this.facing = this.facing === "environment" ? "user" : "environment";
    await this.start();
  }

  stop() {
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.video.srcObject = null;
  }

  get active() {
    return Boolean(this.stream);
  }

  /** Fotograma actual como JPEG (lado mayor limitado a maxSide). */
  capture(maxSide = 1920, quality = 0.92) {
    const w = this.video.videoWidth;
    const h = this.video.videoHeight;
    if (!w || !h) return Promise.reject(new Error("La cámara aún no está lista."));
    const scale = Math.min(1, maxSide / Math.max(w, h));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(w * scale);
    canvas.height = Math.round(h * scale);
    canvas.getContext("2d").drawImage(this.video, 0, 0, canvas.width, canvas.height);
    return new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("No se pudo capturar."))), "image/jpeg", quality));
  }
}

const NO_CAMERA = {
  NotAllowedError: "Permiso de cámara denegado. Actívalo en la configuración del navegador.",
  NotFoundError: "No se encontró ninguna cámara en este equipo.",
  NotReadableError: "La cámara está siendo usada por otra aplicación.",
};

export function cameraError(error) {
  return NO_CAMERA[error && error.name] || `No se pudo abrir la cámara: ${error && error.message}`;
}
