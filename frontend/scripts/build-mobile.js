// Builds the web app for the Capacitor shell and copies it into the native projects.
// The app runs from https://localhost on the device, so it must call the deployed API.
const { execSync } = require("child_process");

const env = {
  ...process.env,
  REACT_APP_BACKEND_URL: process.env.MOBILE_BACKEND_URL || "https://api.arevei.com",
  GENERATE_SOURCEMAP: "false",
};

execSync("npx craco build", { stdio: "inherit", env });
execSync("npx cap sync", { stdio: "inherit", env });
