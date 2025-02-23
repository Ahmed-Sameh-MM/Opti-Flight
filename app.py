from smolagents import CodeAgent, HfApiModel, load_tool, tool
from datetime import datetime
import pytz
import yaml
import os
from typing import List

from tools.final_answer import FinalAnswerTool

from Gradio_UI import GradioUI

from amadeus import Client, ResponseError

from dotenv import load_dotenv


load_dotenv(dotenv_path='creds.env')

# Initialize the Amadeus client
amadeus = Client(
    client_id=os.getenv('AMADEUS_API_KEY'),  # Your Amadeus API Client Key
    client_secret=os.getenv('AMADEUS_API_SECRET')  # Your Amadeus API Client Secret
)

# Below is an example of a tool that does something. Amaze us with your creativity !
@tool
def get_flights_data(source: str, destination: str, date: str, is_flights_direct: bool = False, currency: str = 'USD', price_weight: int = 0, duration_weight: int = 0, late_arrival_weight: int = 0, early_departure_weight: int = 0, non_direct_flight_weight: int = 0) -> List: # it's important to specify the return type
    # Keep this format for the description / args / args description but feel free to modify the tool
    """
    Fetches flight data based on source, destination, and date.

    If no source/destination airport was provided, then select the most used airport in the country.
    If no date was specified, just make the query date tomorrow.

    The Rating Weights defines the relative importance of various flight attributes, it also allows customization of how different flight attributes influence the final rating. For instance, if the user values lower prices above all else, the `priceWeight` will have a higher value, making cheaper flights more favorable in the final sorted results.

    The lower the rating of a flight, the better it is.

    Return the list of flights in this format f'{index from 1 to length of flights}- ({flight_info['airline']}, {flight_info['flight_number']}, {flight_info['is_direct']}) Price: {flight_info['price']}, Departure: {flight_info['departure']}, Arrival: {flight_info['arrival']}\n'

    Args:
        source: IATA code for the source airport (e.g., "JFK").
        destination: IATA code for the destination airport (e.g., "LAX").
        date: Departure date in YYYY-MM-DD format.
        is_flights_direct: If set to true, only flights going from the origin to the destination with no stop in between will be returned (Direct), default value is False
        currency: The preferred currency for the flight offers. Currency is specified in the ISO 4217 format, e.g. EUR for Euro, default is USD

        The Rating Weights attributes include:
        price_weight: Determines the importance of the flight price in the rating. Higher values prioritize cheaper flights.
        duration_weight: Determines the weight of the flight duration in the rating. Longer flights are penalized more with higher values.
        late_arrival_weight: Defines the penalty for late arrivals. Higher values mean a greater penalty for flights arriving late.
        early_departure_weight: Determines the penalty for early departures. Higher values penalize flights departing earlier than scheduled.
        non_direct_flight_weight: Controls the penalty for non-direct flights. Higher values penalize flights with layovers more heavily.

    Returns:
        list: A list of flight data dictionaries, each containing flight details (price, departure/arrival times, airline,
              flight number, and rating). The flights are sorted by rating (lowest rating first).
    """

    class RatingWeights:
        def __init__(self, price_weight: int = 0, duration_weight: int = 0, late_arrival_weight: int = 0,
                     early_departure_weight: int = 0, non_direct_flight_weight: int = 0):
            # Rating parameters (weights ranges from 0 to 5)
            self.priceWeight = price_weight  # Higher weight for price
            self.durationWeight = duration_weight  # Moderate weight for duration
            self.lateArrivalWeight = late_arrival_weight  # Weight for late arrival
            self.earlyDepartureWeight = early_departure_weight  # Weight for early departure
            self.nonDirectFlightWeight = non_direct_flight_weight  # Weight for a non-direct flight

            self._correct_weights()

            self._normalize_weights()

        def _correct_weights(self):
            self.minValue = 0
            self.maxValue = 5

            # Correct any weight that is out of bounds to be between 0 and 5
            self.priceWeight = max(self.minValue, min(self.priceWeight, self.maxValue))
            self.durationWeight = max(self.minValue, min(self.durationWeight, self.maxValue))
            self.lateArrivalWeight = max(self.minValue, min(self.lateArrivalWeight, self.maxValue))
            self.earlyDepartureWeight = max(self.minValue, min(self.earlyDepartureWeight, self.maxValue))
            self.nonDirectFlightWeight = max(self.minValue, min(self.nonDirectFlightWeight, self.maxValue))

        def _normalize_weights(self):
            # Calculate the sum of all weights
            weights_sum = self.priceWeight + self.durationWeight + self.lateArrivalWeight + self.earlyDepartureWeight + self.nonDirectFlightWeight

            # Check if the total weight is not zero to avoid division by zero
            if weights_sum != 0:
                # Normalize the weights by dividing each one by the total weight
                self.priceWeight /= weights_sum
                self.durationWeight /= weights_sum
                self.lateArrivalWeight /= weights_sum
                self.earlyDepartureWeight /= weights_sum
                self.nonDirectFlightWeight /= weights_sum
            else:
                print("Warning: The sum of the weights is zero. Cannot normalize.")

    try:
        # Search for flights
        response = amadeus.shopping.flight_offers_search.get(
            originLocationCode=source,
            destinationLocationCode=destination,
            departureDate=date,
            adults=1,  # Number of adult passengers
            currencyCode=currency,
            # nonStop=is_flights_direct,
            max=20,
        )

        rating_weights = RatingWeights(
            price_weight=price_weight,
            duration_weight=duration_weight,
            late_arrival_weight=late_arrival_weight,
            early_departure_weight=early_departure_weight,
            non_direct_flight_weight=non_direct_flight_weight,
        )

        def calculate_rating(flight) -> float:
            # Extract flight details
            price = float(flight['price']['total'])
            departure_time = datetime.fromisoformat(flight['itineraries'][0]['segments'][0]['departure']['at'])
            arrival_time = datetime.fromisoformat(flight['itineraries'][0]['segments'][-1]['arrival']['at'])

            isFlightNonDirect = 20 if len(flight['itineraries'][0]['segments']) > 1 else 0

            # Calculate duration in hours
            duration = (arrival_time - departure_time).total_seconds() / 3600

            # Late arrival penalty (arrival after 10 PM = lower rating)
            late_arrival_penalty = 0
            if arrival_time.hour >= 22:  # 10 PM
                late_arrival_penalty = 20  # Deduct 20 points for late arrival

            # Early departure penalty (departure before 6 AM = lower rating)
            early_departure_penalty = 0
            if departure_time.hour < 6:  # 6 AM
                early_departure_penalty = 20  # Deduct 20 point for early departure

            # Calculate overall rating
            rating = (
                    (rating_weights.priceWeight * price) +
                    (rating_weights.durationWeight * duration) +
                    (rating_weights.lateArrivalWeight * late_arrival_penalty) +
                    (rating_weights.earlyDepartureWeight * early_departure_penalty) +
                    (rating_weights.nonDirectFlightWeight * isFlightNonDirect)
            )

            return round(rating, 2)  # Round to 2 decimal places

        # Parse the response and calculate ratings
        flights = []
        for index, flight in enumerate(response.data):
            flight_info = {
                "price": flight['price']['total'],
                "departure": datetime.fromisoformat(flight['itineraries'][0]['segments'][0]['departure']['at']).strftime("%d/%m/%Y %H:%M"),
                "arrival": datetime.fromisoformat(flight['itineraries'][0]['segments'][-1]['arrival']['at']).strftime("%d/%m/%Y %H:%M"),
                "airline": flight['itineraries'][0]['segments'][0]['carrierCode'],
                "flight_number": flight['itineraries'][0]['segments'][0]['number'],
                "is_direct": False if len(flight['itineraries'][0]['segments']) > 1 else True,
                "rating": calculate_rating(flight)  # Add rating
            }
            flights.append(flight_info)

        # Sort flights by rating (lowest first)
        flights.sort(key=lambda x: x['rating'])

        # return "What magic will you build ?"
        return flights

    except ResponseError as error:
        print(f"Error fetching flight data: {error}")
        return []

@tool
def get_current_time_in_timezone(timezone: str) -> str:
    """A tool that fetches the current local time in a specified timezone.
    Args:
        timezone: A string representing a valid timezone (e.g., 'America/New_York').
    """
    try:
        # Create timezone object
        tz = pytz.timezone(timezone)
        # Get current time in that timezone
        local_time = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        return f"The current local time in {timezone} is: {local_time}"

    except Exception as e:
        return f"Error fetching time for timezone '{timezone}': {str(e)}"


final_answer = FinalAnswerTool()

model_id = 'Qwen/Qwen2.5-Coder-32B-Instruct'

# If the agent does not answer, the model is overloaded, please use another model or the following Hugging Face Endpoint that also contains qwen2.5 coder:
model_id='https://pflgm2locj2t89co.us-east-1.aws.endpoints.huggingface.cloud'

model = HfApiModel(
    max_tokens=2096,
    temperature=0.5,
    model_id=model_id,  # it is possible that this model may be overloaded
    custom_role_conversions=None,
)

# Import tool from Hub
image_generation_tool = load_tool("agents-course/text-to-image", trust_remote_code=True)

with open("prompts.yaml", 'r') as stream:
    prompt_templates = yaml.safe_load(stream)

agent = CodeAgent(
    model=model,
    tools=[get_flights_data, get_current_time_in_timezone, image_generation_tool, final_answer],  ## add your tools here (don't remove final answer)
    max_steps=6,
    verbosity_level=1,
    grammar=None,
    planning_interval=None,
    name=None,
    description=None,
    prompt_templates=prompt_templates,
)

GradioUI(agent).launch()

# Prompt #1: List flights from Egypt airport to Germany airport, 1st of March 2025
# Prompt #2: List flights from Egypt airport to London airport, 1st of March 2025, make the price weight 5, duration weight 3, late arrival weight 5, non-direct weight 2
