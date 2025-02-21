from smolagents import CodeAgent, HfApiModel, load_tool, tool
from datetime import datetime
import pytz
import yaml
import os
from typing import List
from tools.final_answer import FinalAnswerTool

from Gradio_UI import GradioUI

from amadeus import Client, ResponseError


# Initialize the Amadeus client
amadeus = Client(
    client_id=os.getenv('AMADEUS_API_KEY'),  # Your Amadeus API Client Key
    client_secret=os.getenv('AMADEUS_API_SECRET')  # Your Amadeus API Client Secret
)

def calculate_rating(flight) -> float:
    """
    Calculates a rating (1-5) for a flight based on price, duration, late arrival, and early departure.

    Args:
        flight (dict): Flight data including price, departure, and arrival times.

    Returns:
        float: Overall rating (1-5).
    """
    # Extract flight details
    price = float(flight['price']['total'])
    departure_time = datetime.fromisoformat(flight['itineraries'][0]['segments'][0]['departure']['at'])
    arrival_time = datetime.fromisoformat(flight['itineraries'][0]['segments'][-1]['arrival']['at'])

    isFlightNonDirect = 20 if len(flight['itineraries'][0]['segments']) > 1 else 0

    # Calculate duration in hours
    duration = (arrival_time - departure_time).total_seconds() / 3600

    # Rating parameters (weights ranges from 0 to 5)
    price_weight = 0  # Higher weight for price
    duration_weight = 0  # Moderate weight for duration
    late_arrival_weight = 0  # Weight for late arrival
    early_departure_weight = 0  # Weight for early departure
    non_direct_flight_weight = 0  # Weight for a non-direct flight

    weights_sum = price_weight + duration_weight + late_arrival_weight + early_departure_weight + non_direct_flight_weight
    
    if weights_sum != 0:
        price_weight /= weights_sum
        duration_weight /= weights_sum
        late_arrival_weight /= weights_sum
        early_departure_weight /= weights_sum
        non_direct_flight_weight /= weights_sum

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
        (price_weight * price) +
        (duration_weight * duration) +
        (late_arrival_weight * late_arrival_penalty) +
        (early_departure_weight * early_departure_penalty) +
        (non_direct_flight_weight * isFlightNonDirect)
    )

    return round(rating, 2)  # Round to 2 decimal places

# Below is an example of a tool that does something. Amaze us with your creativity !
@tool
def get_flights_data(source: str, destination: str, date: str) -> List: # it's important to specify the return type
    # Keep this format for the description / args / args description but feel free to modify the tool
    """
    Fetches flight data based on source, destination, date, and time.

    Args:
        source: IATA code for the source airport (e.g., "JFK").
        destination: IATA code for the destination airport (e.g., "LAX").
        date: Departure date in YYYY-MM-DD format.

    Returns:
        list: A list of flight data (price, datetime, rating, etc.).
    """
    try:
        # Search for flights
        response = amadeus.shopping.flight_offers_search.get(
            originLocationCode=source,
            destinationLocationCode=destination,
            departureDate=date,
            adults=1,  # Number of adult passengers
        )

        # Parse the response and calculate ratings
        flights = []
        for flight in response.data:
            flight_info = {
                "price": flight['price']['total'],
                "departure": flight['itineraries'][0]['segments'][0]['departure']['at'],
                "arrival": flight['itineraries'][0]['segments'][-1]['arrival']['at'],
                "airline": flight['itineraries'][0]['segments'][0]['carrierCode'],
                "flight_number": flight['itineraries'][0]['segments'][0]['number'],
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
    prompt_templates=prompt_templates
)

GradioUI(agent).launch()
