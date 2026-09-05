import { RouterProvider } from "react-router-dom";
import { Provider } from "@/app/provider";
import { router } from "@/app/router";

export function App() {
  return (
    <Provider>
      <RouterProvider router={router} />
    </Provider>
  );
}
