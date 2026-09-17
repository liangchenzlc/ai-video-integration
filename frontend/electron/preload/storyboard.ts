import { z } from "zod";
import { checked } from "./projects";
import { storyboardRoutes, type StoryboardBridge } from "../shared/storyboard";

export const storyboardBridge = Object.freeze(
  Object.fromEntries(
    Object.entries(storyboardRoutes).map(([name, route]) => [
      name,
      (input: unknown) =>
        checked(
          `storyboard:${name}`,
          input,
          route.input as z.ZodType,
          route.output as z.ZodType,
        ),
    ]),
  ),
) as StoryboardBridge;
