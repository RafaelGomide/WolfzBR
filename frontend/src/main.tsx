import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@glideapps/glide-data-grid/dist/index.css";
import "./estilo.css";
import { App } from "./App";
import { Barreira } from "./componentes/Estado";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Barreira>
      <App />
    </Barreira>
  </StrictMode>,
);
