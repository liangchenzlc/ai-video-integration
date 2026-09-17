import React from "react";
import { createRoot } from "react-dom/client";
import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { App } from "./app/App";
import "./app/styles.css";
import "./app/studio.css";
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider
      autoInsertSpaceInButton={false}
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#1677ff",
          colorBgLayout: "#f5f8fc",
          colorBorder: "#d9e3ef",
          colorText: "#20334d",
          colorTextPlaceholder: "#586f8a",
          fontFamily: '"Microsoft YaHei UI", "Segoe UI", sans-serif',
        },
        components: {
          Button: {
            colorPrimary: "#0958d9",
            colorPrimaryHover: "#084ab4",
            colorPrimaryActive: "#003eb3",
          },
        },
      }}
    >
      <App />
    </ConfigProvider>
  </React.StrictMode>,
);
