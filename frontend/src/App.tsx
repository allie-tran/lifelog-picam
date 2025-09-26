import React from "react";
import "./App.css";
import useSWR from "swr";
import axios from "axios";
import {
  Badge,
  Box,
  Button,
  Modal,
  Pagination,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import {
  LocalizationProvider,
  PickersDay,
  PickersDayProps,
} from "@mui/x-date-pickers";
import { AdapterDayjs } from "@mui/x-date-pickers/AdapterDayjs";
import dayjs, { Dayjs } from "dayjs";

const BASE_URL = `${window.location.origin}/${window.location.pathname.split("/")[1]}`;
let BACKEND_URL = `${BASE_URL}/be`;
let IMAGE_HOST_URL = `${window.location.origin}/images/LifelogPicam/`;

if (window.location.hostname === "localhost") {
  BACKEND_URL = `http://localhost:8082`;
  IMAGE_HOST_URL = `http://localhost:9000/LifelogPicam/`;
}

const THUMBNAIL_HOST_URL = `${IMAGE_HOST_URL}thumbnails/`;

const getImages = async (page: number = 1, date?: string) => {
  const response = await axios.get(
    `${BACKEND_URL}/get-images?page=${page}${date ? `&date=${date}` : ""}`,
  );
  return response.data as {
    date: string;
    images: ImageData[];
    total_pages: number;
  };
};

const getAllDates = async () => {
  const response = await axios.get(`${BACKEND_URL}/get-all-dates`);
  console.log("response", response.data);
  return response.data as string[];
};

const searchImages = async (query: string) => {
  const response = await axios.get(
    `${BACKEND_URL}/search-images?query=${query}`,
  );
  return response.data as ImageData[];
};

const AvailableDay = (props: PickersDayProps & { allDates: string[] }) => {
  const { allDates = [], day, outsideCurrentMonth, ...other } = props;

  const isSelected =
    !props.outsideCurrentMonth && allDates.includes(day.format("YYYY-MM-DD"));

  if (!allDates.includes(day.format("YYYY-MM-DD"))) {
    return (
      <PickersDay
        {...other}
        day={day}
        outsideCurrentMonth={outsideCurrentMonth}
      />
    );
  }

  return (
    <Badge key={day.toString()} variant="dot" color="primary">
      <PickersDay
        {...other}
        day={day}
        outsideCurrentMonth={outsideCurrentMonth}
      />
    </Badge>
  );
};

function App() {
  const [page, setPage] = React.useState(1);
  const [date, setDate] = React.useState<Dayjs | null>(dayjs());
  const [selectedImage, setSelectedImage] = React.useState<string | null>(null);
  const { data, error } = useSWR(
    [page, date],
    () => getImages(page, date ? date.format("YYYY-MM-DD") : undefined),
    {
      revalidateOnFocus: false,
    },
  );

  const { data: allDates } = useSWR("all-dates", getAllDates, {
    revalidateOnFocus: false,
  });

  const images = data?.images;

  return (
    <PasswordLock>
      <LocalizationProvider dateAdapter={AdapterDayjs}>
        <Stack spacing={2} alignItems="center" sx={{ padding: 2 }} id="app">
          <Typography variant="h4" color="primary" fontWeight="bold">
            {data?.date || "All Dates"}
          </Typography>
          <DatePicker
            label="Select Date"
            value={date}
            onChange={(newValue) => {
              setDate(newValue);
              setPage(1);
            }}
            slots={{
              day: (props) => (
                <AvailableDay {...props} allDates={allDates || []} />
              ),
            }}
          />
          <SearchInterface />
          {error && <div>Failed to load images</div>}
          {!images && !error && <div>Loading...</div>}
          {images && (
            <div className="image-grid">
              {images.map((image: ImageData) => (
                <ImageWithDate
                  key={image.image_path}
                  imagePath={image.image_path}
                  timestamp={image.timestamp}
                  onClick={() =>
                    setSelectedImage(`${IMAGE_HOST_URL}/${image.image_path}.jpg`)
                  }
                />
              ))}
            </div>
          )}
          <Pagination
            count={data?.total_pages || 1}
            color="primary"
            onChange={(_, page) => {
              setPage(page);
              const element = document.getElementById("app");
              element?.scrollIntoView({ behavior: "smooth" });
            }}
          />
        </Stack>
        {selectedImage && (
          <ImageZoom
            imageUrl={selectedImage}
            onClose={() => setSelectedImage(null)}
          />
        )}
      </LocalizationProvider>
    </PasswordLock>
  );
}

const SearchInterface = () => {
  const [query, setQuery] = React.useState("");
  const [results, setResults] = React.useState<ImageData[]>([]);
  const [open, setOpen] = React.useState(false);
  const onSearch = (query: string) => {
    searchImages(query).then((data) => {
      setResults(data);
    });
  };

  return (
    <Stack direction="row" spacing={2} alignItems="center">
      <TextField
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search images..."
        sx={{ padding: "8px", width: "80dvw", marginRight: "8px" }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            onSearch(query);
            setOpen(true);
          }
        }}
      />
      <Button
        variant="outlined"
        onClick={() => {
          onSearch(query);
          setOpen(true);
        }}
        sx={{ padding: "8px" }}
      >
        Search
      </Button>
      <ModalWithCloseButton open={open} onClose={() => setOpen(false)}>
        {results.length === 0 && <div>No results found</div>}
        <Stack
          spacing={2}
          sx={{ width: "100%", flexWrap: "wrap" }}
          direction="row"
          useFlexGap
        >
          {results.map((image) => (
            <ImageWithDate
              key={image.image_path}
              imagePath={image.image_path}
              timestamp={image.timestamp}
            />
          ))}
        </Stack>
      </ModalWithCloseButton>
    </Stack>
  );
};

const ImageZoom = ({
  imageUrl,
  onClose,
}: {
  imageUrl: string;
  onClose: () => void;
}) => {
  return (
    <ModalWithCloseButton open={true} onClose={onClose}>
      <img
        src={imageUrl}
        alt="Zoomed"
        style={{ maxWidth: "100%", height: "auto", borderRadius: "8px" }}
      />
    </ModalWithCloseButton>
  );
};

const ModalWithCloseButton = ({
  children,
  open,
  onClose,
}: {
  children: React.ReactNode;
  onClose: () => void;
  open: boolean;
}) => {
  return (
    <Modal open={open} onClose={onClose}>
      <Box
        sx={{
          position: "absolute",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          bgcolor: "background.paper",
          boxShadow: 24,
          p: 4,
          maxHeight: "80vh",
          width: "80vw",
          overflowY: "auto",
          borderRadius: "8px",
        }}
      >
        <Button
          onClick={onClose}
          sx={{ position: "absolute", top: 8, right: 8 }}
        >
          <CloseIcon />
        </Button>
        {children}
      </Box>
    </Modal>
  );
};

type ImageData = {
  image_path: string;
  timestamp: string;
};

const ImageWithDate = ({
  imagePath,
  timestamp,
  onClick,
}: {
  imagePath: string;
  timestamp: string;
  onClick?: () => void;
}) => {
  const imageUrl = `${THUMBNAIL_HOST_URL}/${imagePath}.webp`;
  const date = new Date(timestamp);
  const formattedDate = date.toLocaleString();
  return (
    <div style={{ marginBottom: "20px" }}>
      <img
        src={imageUrl}
        alt={imagePath}
        style={{
          maxWidth: "clamp(150px, 33vw, 300px)",
          height: "auto",
          borderRadius: "8px",
        }}
        onClick={onClick}
      />
      <div>{formattedDate}</div>
    </div>
  );
};

const PasswordLock = ({ children }: { children: React.ReactNode }) => {
  const [password, setPassword] = React.useState("");
  const [isAuthenticated, setIsAuthenticated] = React.useState(false);

  const handlePasswordSubmit = () => {
    const url = `${BACKEND_URL}/login?password=${encodeURIComponent(password)}`;
    axios
      .get(url)
      .then((response) => {
        if (response.data.success) {
          setIsAuthenticated(true);
        }
      })
      .catch((error) => {
        console.error("There was an error logging in!", error);
        alert("Incorrect password. Please try again.");
      });
  };

  if (isAuthenticated) {
    return <>{children}</>;
  }

  return (
    <ModalWithCloseButton open={true} onClose={() => {}}>
      <Stack spacing={2} alignItems="center">
        <Typography variant="h6">Enter Password to Access</Typography>
        <TextField
          type="password"
          label="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          sx={{ width: "300px" }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              handlePasswordSubmit();
            }
          }}
        />
        <Button variant="contained" onClick={handlePasswordSubmit}>
          Submit
        </Button>
      </Stack>
    </ModalWithCloseButton>
  );
};

export default App;
