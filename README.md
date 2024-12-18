<a id="readme-top"></a>

[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]

<h3 align="center">CityBot2</h3>

CityBot2 is a Python-based application designed to create social media posts for a local area. The initial version supports news source RSS feeds and government data on weather and earthquakes. It can post to Bluesky, Facebook, LinkedIn, and Twitter/X.

You can download it to your server and schedule it to run with city-specific customizations. Testing and improvements are welcome!

This is a major upgrade and full rewrite of the original [CityBot](https://github.com/ericrosenberg1/CityBot) (archived).

[![Snyk](https://snyk.io/test/github/ericrosenberg1/CityBot2/badge.svg)](https://snyk.io/test/github/ericrosenberg1/CityBot2)
[![Maintainability](https://api.codeclimate.com/v1/badges/4857f450946330748975/maintainability)](https://codeclimate.com/github/ericrosenberg1/CityBot2/maintainability)
[![Test Coverage](https://api.codeclimate.com/v1/badges/4857f450946330748975/test_coverage)](https://codeclimate.com/github/ericrosenberg1/CityBot2/test_coverage)
[![Codacy Badge](https://app.codacy.com/project/badge/Grade/efb5beefe547465087883828710a7a11)](https://app.codacy.com/gh/ericrosenberg1/CityBot2/dashboard?utm_source=gh&utm_medium=referral&utm_content=&utm_campaign=Badge_grade)

<details>
  <summary>Table of Contents</summary>
  <ol>
    <li><a href="#built-with">Built With</a></li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li><a href="#dependencies">Dependencies</a></li>
    <li><a href="#usage">Usage</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#contributors">Contributors</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>

### Built With
<img src="https://img.shields.io/badge/Python-FFD43B?style=for-the-badge&logo=python&logoColor=blue" />

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Getting Started

**Disclaimer:** This app comes with no warranties or guarantees. Use it at your own risk. It's recommended to use a virtual environment to keep your dependencies isolated from the rest of your system.

### Prerequisites

- Ensure you have a recent version of Python installed.
- Create and activate a virtual environment.
- Update `pip`.

Example:
```sh
mkdir CityBot2
cd CityBot2
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
```

### Installation

1. **Clone the repository:**
   ```sh
   git clone https://github.com/ericrosenberg1/CityBot2
   cd CityBot2
   ```

2. **Install dependencies:**
   ```sh
   pip install -r requirements.txt
   ```

3. **Configure city and credentials:**
   ```sh
   cd config
   mv credentials.env.example credentials.env
   nano credentials.env
   ```
   Update credentials and save.
   
   Update city configuration:
   ```sh
   nano city_example.json
   ```
   Set your city details, save, and exit.

4. **Run the app:**
   ```sh
   cd ..
   python main.py
   ```
   
5. **View logs:**
   ```sh
   tail -f logs/citybot.log
   ```

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Dependencies

CityBot2 may require system dependencies for mapping and geospatial support. On Debian/Ubuntu systems, you might need:
- python3-pip
- python3-dev
- build-essential
- libatlas-base-dev
- gfortran
- libgeos-dev
- libproj-dev
- proj-data
- proj-bin
- libcairo2-dev
- pkg-config
- python3-cartopy
- cutycapt

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Usage

After configuration and installation, run `python main.py` to start the bot. Check `logs/citybot.log` for activity and error messages.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Roadmap

- [ ] Create documentation
- [ ] Improve error handling
- [ ] Create a basic web GUI
- [ ] Make it easier to update city configurations
- [ ] Publish on PyPi or provide apt install method

See the [open issues](https://github.com/ericrosenberg1/CityBot2/issues) for a full list of proposed features and known issues.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Contributing

Contributions are welcome! If you find a bug or have a suggestion, open an issue or create a pull request.

1. Fork the Project
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

Stars are appreciated!

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Contributors

<a href="https://github.com/ericrosenberg1/CityBot2/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=ericrosenberg1/CityBot2" />
</a>

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## License

Distributed under the GPLv3 License. See `LICENSE.txt` for more information.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Acknowledgments

* Claude.ai for initial code assistance
* [GPT4Readability](https://github.com/loevlie/GPT4Readability) for inspiration
* [Best-README-Template](https://github.com/othneildrew/Best-README-Template/tree/main) for README structure

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- MARKDOWN LINKS & IMAGES -->
[contributors-shield]: https://img.shields.io/github/contributors/ericrosenberg1/CityBot2.svg?style=for-the-badge
[contributors-url]: https://github.com/ericrosenberg1/CityBot2/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/ericrosenberg1/CityBot2.svg?style=for-the-badge
[forks-url]: https://github.com/ericrosenberg1/CityBot2/network/members
[stars-shield]: https://img.shields.io/github/stars/ericrosenberg1/CityBot2.svg?style=for-the-badge
[stars-url]: https://github.com/ericrosenberg1/CityBot2/stargazers
[issues-shield]: https://img.shields.io/github/issues/ericrosenberg1/CityBot2.svg?style=for-the-badge
[issues-url]: https://github.com/ericrosenberg1/CityBot2/issues
