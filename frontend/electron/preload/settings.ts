import { receiptSchema } from "../shared/projects";
import { projectInputSchema } from "../shared/drafts";
import { jobSchema } from "../shared/media";
import {
  settingsSchema,
  settingsDetailsSchema,
  setCredentialSchema,
  deleteCredentialSchema,
  storageCommandSchema,
  configureStageSchema,
  stageModelsSchema,
  connectionCheckSchema,
  globalJobInputSchema,
  type SettingsBridge,
} from "../shared/settings";
import { invoke, checked } from "./projects";
export const settingsBridge: SettingsBridge = Object.freeze({
  get: () => invoke("settings:get", settingsSchema),
  details: () => invoke("settings:details", settingsDetailsSchema),
  setCredential: (input: unknown) =>
    checked(
      "settings:set-credential",
      input,
      setCredentialSchema,
      receiptSchema,
    ),
  deleteCredential: (input: unknown) =>
    checked(
      "settings:delete-credential",
      input,
      deleteCredentialSchema,
      receiptSchema,
    ),
  configureStorage: (input: unknown) =>
    checked(
      "settings:configure-storage",
      input,
      storageCommandSchema,
      receiptSchema,
    ),
  configureStage: (input: unknown) =>
    checked(
      "settings:configure-stage",
      input,
      configureStageSchema,
      receiptSchema,
    ),
  stageModels: (input: unknown) =>
    checked(
      "settings:stage-models",
      input,
      projectInputSchema,
      stageModelsSchema,
    ),
  checkConnection: (input: unknown) =>
    checked(
      "settings:check-connection",
      input,
      connectionCheckSchema,
      receiptSchema,
    ),
  job: (input: unknown) =>
    checked("settings:job", input, globalJobInputSchema, jobSchema),
});
