import { checked } from "./projects";
import { z } from "zod";
import { taskRoutes, type TasksBridge } from "../shared/tasks";
export const tasksBridge = Object.freeze(
  Object.fromEntries(
    Object.entries(taskRoutes).map(([name, route]) => [
      name,
      (input: unknown) =>
        checked(
          `tasks:${name}`,
          input,
          route.input as z.ZodType,
          route.output as z.ZodType,
        ),
    ]),
  ),
) as TasksBridge;
