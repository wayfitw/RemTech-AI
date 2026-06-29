import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import "@fontsource-variable/inter/wght.css";
import "@tabler/icons-webfont/dist/tabler-icons.min.css";
import "./styles.css";

document.documentElement.setAttribute(
  "data-theme",
  localStorage.getItem("theme") || "dark"
);

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
