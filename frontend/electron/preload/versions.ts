import { z } from "zod";
import { checked } from "./projects";
import { versionRoutes, type VersionsBridge } from "../shared/versions";

export const versionsBridge = Object.freeze(
  Object.fromEntries(
    Object.entries(versionRoutes).map(([name, route]) => [
      name,
      (input: unknown) =>
        checked(
          `versions:${name}`,
          input,
          route.input as z.ZodType,
          route.output as z.ZodType,
        ),
    ]),
  ),
) as VersionsBridge;
